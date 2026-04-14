"""
Local reviewer pipeline for GitHub pull requests.

The reviewer runs entirely on the worker:
- clone/fetch the repository locally
- build a tree-sitter-backed JSON snapshot of repository files
- fetch PR file diffs and parse diff hunks
- extract relevant code snippets from the repository AST and diff snippets
- ask the LLM for review comments / verdict
- post inline comments and a final review to GitHub
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

from agents.github_llm import get_github_deep_agent_llm
from logger import get_logger
from services.github.client import (
    comment_on_pr,
    create_pr_review_comment,
    list_pr_issue_comments,
    list_pr_review_comments,
    list_pr_review_files,
    submit_pr_review,
)
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)

_MAX_PREVIOUS_COMMENTS = 25
_MAX_FILE_SNAPSHOT_BYTES = 250_000
_MAX_REFERENCE_DEPTH = 3

_IDENTIFIER_NODE_TYPES = (
    "identifier",
    "property_identifier",
    "type_identifier",
    "field_identifier",
    "shorthand_property_identifier",
    "simple_identifier",
)
_FUNCTION_NODE_TYPES = {
    "function_definition",
    "function_declaration",
    "method_definition",
    "method_declaration",
    "arrow_function",
}
_CLASS_NODE_TYPES = {
    "class_definition",
    "class_declaration",
    "struct_declaration",
    "protocol_declaration",
    "enum_declaration",
    "type_declaration",
}
_IMPORT_NODE_TYPES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "import_spec",
}
_CALL_NODE_TYPES = {
    "call",
    "call_expression",
    "function_call_expression",
}

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".sql": "sql",
}


@dataclass
class DiffLine:
    kind: Literal["context", "add", "del"]
    old_line: int | None
    new_line: int | None
    text: str


@dataclass
class DiffHunk:
    header: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]

    @property
    def added_new_lines(self) -> list[int]:
        return [
            line.new_line for line in self.lines if line.kind == "add" and line.new_line
        ]

    @property
    def deleted_old_lines(self) -> list[int]:
        return [
            line.old_line for line in self.lines if line.kind == "del" and line.old_line
        ]

    @property
    def right_commentable_lines(self) -> list[int]:
        return [
            line.new_line
            for line in self.lines
            if line.kind in ("context", "add") and line.new_line
        ]

    @property
    def left_commentable_lines(self) -> list[int]:
        return [
            line.old_line
            for line in self.lines
            if line.kind in ("context", "del") and line.old_line
        ]

    def new_code(self) -> str:
        return "\n".join(line.text for line in self.lines if line.kind != "del")

    def old_code(self) -> str:
        return "\n".join(line.text for line in self.lines if line.kind != "add")


@dataclass
class PullRequestFileDiff:
    path: str
    status: str
    patch: str
    previous_filename: str | None
    language: str | None
    hunks: list[DiffHunk]

    @property
    def right_commentable_lines(self) -> set[int]:
        out: set[int] = set()
        for hunk in self.hunks:
            out.update(hunk.right_commentable_lines)
        return out

    @property
    def left_commentable_lines(self) -> set[int]:
        out: set[int] = set()
        for hunk in self.hunks:
            out.update(hunk.left_commentable_lines)
        return out


@dataclass
class ParsedFile:
    path: str
    language: str | None
    text: str | None
    lines: list[str] | None
    tree: Any | None
    symbol_snapshot: dict[str, Any]
    function_symbols: list[dict[str, Any]]
    class_symbols: list[dict[str, Any]]
    import_symbols: list[dict[str, Any]]
    call_symbols: list[dict[str, Any]]


@dataclass
class RepositorySnapshot:
    repo_dir: Path
    snapshot_path: Path
    files: dict[str, ParsedFile]
    file_inventory: list[dict[str, Any]]
    symbol_index: dict[str, list[dict[str, Any]]]


class ReviewInlineComment(BaseModel):
    path: str = Field(..., description="The file path of the inline comment.")
    line: int = Field(
        ...,
        description="The line number (1-based) on which to comment on the specified side.",
    )
    body: str = Field(..., description="Content body of the inline comment.")
    side: Literal["RIGHT", "LEFT"] = Field(
        "RIGHT",
        description="Diff side: 'RIGHT' for head branch, 'LEFT' for base branch.",
    )
    start_line: int | None = Field(
        None,
        description="(Optional) The first line of a multi-line comment range, using the same side.",
    )
    start_side: Literal["RIGHT", "LEFT"] | None = Field(
        None,
        description="(Optional) If given, should match 'side'. Used for multi-line comments.",
    )


class ReviewDecision(BaseModel):
    summary: str = Field(..., description="Short human-readable review summary.")
    review_event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = "COMMENT"
    review_body: str = Field(..., description="Body for the final PR review event.")
    pr_comment_body: str = Field(
        ..., description="Conversation comment to post on the PR."
    )
    inline_comments: list[ReviewInlineComment] = Field(default_factory=list)


def detect_language(path: str) -> str | None:
    return _LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower())


def _run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed"
        )
    return proc.stdout.strip()


def reviewer_clone_repo_path(pr: PROpenedForReview) -> Path:
    """Directory used for a full clone of ``pr`` under the worker temp dir."""
    base_dir = Path(tempfile.gettempdir()) / "greagent-reviewer"
    return base_dir / f"{pr.owner}__{pr.repo_name}"


def remove_reviewer_clone(pr: PROpenedForReview) -> None:
    """Delete the local clone for this PR so the worker does not accumulate repos."""
    repo_dir = reviewer_clone_repo_path(pr)
    if not repo_dir.exists():
        return
    try:
        shutil.rmtree(repo_dir)
    except OSError as exc:
        logger.warning("Failed to remove reviewer clone at %s: %s", repo_dir, exc)


def clone_or_prepare_repo(pr: PROpenedForReview, token: str) -> Path:
    repo_dir = reviewer_clone_repo_path(pr)
    base_dir = repo_dir.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://x-access-token:{token}@github.com/{pr.full_name}.git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    if not repo_dir.exists():
        _run_git(
            ["clone", "--depth=1", "--single-branch", clone_url, str(repo_dir)],
            env=env,
        )
    else:
        logger.info("Updating existing reviewer clone for %s", repo_dir)
        _run_git(["remote", "set-url", "origin", clone_url], cwd=repo_dir, env=env)
    logger.info("Fetching latest changes from origin for %s", repo_dir)
    _run_git(["fetch", "--prune", "origin"], cwd=repo_dir, env=env)
    logger.info("Fetching PR head branch for %s", repo_dir)
    _run_git(
        [
            "fetch",
            "--depth=1",
            "origin",
            f"pull/{pr.pr_number}/head:greagent/pr-{pr.pr_number}",
        ],
        cwd=repo_dir,
        env=env,
    )
    _run_git(["checkout", "-f", f"greagent/pr-{pr.pr_number}"], cwd=repo_dir, env=env)
    return repo_dir


@lru_cache(maxsize=32)
def _get_tree_sitter_parser(language: str) -> Any | None:
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:
        logger.warning(
            "tree_sitter_language_pack is not installed; AST extraction disabled"
        )
        return None

    try:
        return get_parser(language)
    except Exception:
        return None


def _node_text(source: bytes, node: Any) -> str:
    return source[getattr(node, "start_byte", 0) : getattr(node, "end_byte", 0)].decode(
        "utf-8", errors="ignore"
    )


def _line_span(node: Any) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def _find_first_child_by_type(node: Any, type_names: tuple[str, ...]) -> Any | None:
    for child in getattr(node, "named_children", []):
        if getattr(child, "type", None) in type_names:
            return child
        nested = _find_first_child_by_type(child, type_names)
        if nested is not None:
            return nested
    return None


def _collect_identifier_texts(node: Any, source: bytes) -> list[str]:
    out: list[str] = []
    node_type = getattr(node, "type", None)
    if node_type in _IDENTIFIER_NODE_TYPES:
        text = _node_text(source, node).strip()
        if text:
            out.append(text)
    for child in getattr(node, "named_children", []):
        out.extend(_collect_identifier_texts(child, source))
    return out


def _dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _extract_string_literal_text(node: Any, source: bytes) -> str | None:
    text = _node_text(source, node).strip()
    if len(text) >= 2 and text[0] in {"'", '"', "`"} and text[-1] == text[0]:
        return text[1:-1]
    children = getattr(node, "named_children", [])
    if children:
        joined = "".join(_node_text(source, child) for child in children).strip()
        return joined or None
    return text or None


def _extract_module_name_from_import(node: Any, source: bytes) -> str | None:
    for child in getattr(node, "named_children", []):
        child_type = getattr(child, "type", "")
        if "string" in child_type:
            text = _extract_string_literal_text(child, source)
            if text:
                return text
    for child in getattr(node, "named_children", []):
        child_type = getattr(child, "type", "")
        if child_type in {"dotted_name", "relative_import"}:
            text = _node_text(source, child).strip()
            if text:
                return text
    identifiers = _collect_identifier_texts(node, source)
    return identifiers[0] if identifiers else None


def _extract_symbol_name(language: str | None, node: Any, source: bytes) -> str | None:
    child = _find_first_child_by_type(node, _IDENTIFIER_NODE_TYPES)
    if child is not None:
        text = _node_text(source, child).strip()
        return text or None
    return None


def _extract_import_symbol(
    language: str | None, node: Any, source: bytes
) -> dict[str, Any]:
    code = _node_text(source, node).strip()
    start_line, end_line = _line_span(node)
    identifiers = _dedupe_keep_order(_collect_identifier_texts(node, source))
    module = _extract_module_name_from_import(node, source)
    imported_names = identifiers[:]
    namespace_aliases: list[str] = []
    if module:
        module_leaf = module.rstrip("/").split("/")[-1].split(".")[-1]
        if module_leaf:
            namespace_aliases.append(module_leaf)
        if imported_names and imported_names[0] == module:
            imported_names = imported_names[1:]
        if imported_names and imported_names[0] == module_leaf:
            imported_names = imported_names[1:]
    if language == "go" and module:
        namespace_aliases = [identifiers[0]] if identifiers else namespace_aliases
    if language == "swift" and module:
        namespace_aliases = [module]
    return {
        "code": code,
        "module": module,
        "imported_names": _dedupe_keep_order(imported_names),
        "namespace_aliases": _dedupe_keep_order(namespace_aliases),
        "line_range": [start_line, end_line],
    }


def _extract_call_symbol(
    language: str | None, node: Any, source: bytes
) -> dict[str, Any]:
    start_line, end_line = _line_span(node)
    callee_text = None
    fn = node.child_by_field_name("function")
    if fn is not None:
        callee_text = _node_text(source, fn).strip()
    if not callee_text:
        identifiers = _collect_identifier_texts(node, source)
        if identifiers:
            callee_text = (
                ".".join(identifiers[:2]) if len(identifiers) > 1 else identifiers[0]
            )
    return {
        "name": callee_text,
        "code": _node_text(source, node).strip(),
        "line_range": [start_line, end_line],
    }


def _extract_function_symbol(
    language: str | None, node: Any, source: bytes
) -> dict[str, Any]:
    start_line, end_line = _line_span(node)
    name = _extract_symbol_name(language, node, source)
    code = _node_text(source, node).strip()
    identifiers = _dedupe_keep_order(_collect_identifier_texts(node, source))
    symbol = {
        "name": name,
        "code": code,
        "line_range": [start_line, end_line],
        "calls": [],
        "imports_used": [],
        "identifiers": identifiers,
    }
    return symbol


def _extract_class_symbol(
    language: str | None, node: Any, source: bytes
) -> dict[str, Any]:
    start_line, end_line = _line_span(node)
    return {
        "name": _extract_symbol_name(language, node, source),
        "code": _node_text(source, node).strip(),
        "line_range": [start_line, end_line],
    }


def _walk_named_nodes(node: Any) -> list[Any]:
    out = [node]
    for child in getattr(node, "named_children", []):
        out.extend(_walk_named_nodes(child))
    return out


def _extract_symbols(
    language: str | None, source: bytes, tree: Any
) -> dict[str, list[dict[str, Any]]]:
    root = tree.root_node
    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []

    for node in _walk_named_nodes(root):
        node_type = getattr(node, "type", None)
        if node_type in _FUNCTION_NODE_TYPES:
            functions.append(_extract_function_symbol(language, node, source))
        elif node_type in _CLASS_NODE_TYPES:
            classes.append(_extract_class_symbol(language, node, source))
        elif node_type in _IMPORT_NODE_TYPES:
            imports.append(_extract_import_symbol(language, node, source))
        elif node_type in _CALL_NODE_TYPES:
            calls.append(_extract_call_symbol(language, node, source))

    import_names = {name for imp in imports for name in imp.get("imported_names", [])}
    namespace_aliases = {
        alias for imp in imports for alias in imp.get("namespace_aliases", [])
    }
    for function in functions:
        function["calls"] = [
            call["name"]
            for call in calls
            if call.get("name")
            and function["line_range"][0]
            <= call["line_range"][0]
            <= function["line_range"][1]
        ]
        function_identifiers = set(function.get("identifiers", []))
        for call_name in function["calls"]:
            function_identifiers.update(
                part for part in (call_name or "").split(".") if part
            )
        function["imports_used"] = sorted(
            {
                name
                for name in (import_names | namespace_aliases)
                if name in function_identifiers
            }
        )

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "calls": calls,
    }


def _build_symbol_snapshot(symbols: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "functions": [
            {
                "name": symbol.get("name"),
                "line_range": symbol.get("line_range"),
                "calls": symbol.get("calls", []),
                "imports_used": symbol.get("imports_used", []),
                "code": symbol.get("code"),
            }
            for symbol in symbols["functions"]
        ],
        "classes": [
            {
                "name": symbol.get("name"),
                "line_range": symbol.get("line_range"),
                "code": symbol.get("code"),
            }
            for symbol in symbols["classes"]
        ],
        "imports": symbols["imports"],
        "calls": symbols["calls"],
    }


def _path_to_module_parts(path: str) -> list[str]:
    path_obj = Path(path)
    parts = list(path_obj.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _module_path_candidates(
    importer_path: str, module_name: str, language: str | None
) -> list[str]:
    if not module_name:
        return []
    candidates: list[str] = []
    suffixes = (
        [".py"]
        if language == "python"
        else [".ts", ".tsx", ".js", ".jsx", ".go", ".swift"]
    )
    module_parts = [part for part in module_name.split(".") if part]
    if language in {"javascript", "typescript", "tsx"} and module_name.startswith("."):
        importer_dir = str(Path(importer_path).parent).replace("\\", "/")
        relative = str((Path(importer_dir) / module_name).resolve()).replace("\\", "/")
        return []
    if language == "python" and module_name.startswith("."):
        importer_path_obj = Path(importer_path)
        importer_parts = _path_to_module_parts(importer_path)
        importer_package_parts = (
            importer_parts
            if importer_path_obj.stem == "__init__"
            else importer_parts[:-1]
        )
        leading_dots = len(module_name) - len(module_name.lstrip("."))
        remaining = module_name.lstrip(".")
        rel_parts = [part for part in remaining.split(".") if part]
        trim = max(leading_dots - 1, 0)
        if trim == 0:
            base_parts = importer_package_parts
        else:
            base_parts = (
                importer_package_parts[:-trim]
                if trim <= len(importer_package_parts)
                else []
            )
        module_parts = [*base_parts, *rel_parts]
    if module_parts:
        base = "/".join(module_parts)
        for suffix in suffixes:
            candidates.append(base + suffix)
            candidates.append("/".join(module_parts + ["index"]) + suffix)
        candidates.append("/".join(module_parts + ["__init__"]) + ".py")
    return candidates


def _local_module_candidates(
    importer_path: str, module_name: str, language: str | None
) -> list[str]:
    if not module_name:
        return []
    if language == "python":
        return _module_path_candidates(importer_path, module_name, language)
    if language in {"javascript", "typescript", "tsx"}:
        importer_dir = Path(importer_path).parent
        base = (importer_dir / module_name).as_posix()
        out: list[str] = []
        for suffix in (".ts", ".tsx", ".js", ".jsx"):
            out.append(base + suffix)
            out.append(f"{base}/index{suffix}")
        return out
    if language == "go":
        last_segment = module_name.rstrip("/").split("/")[-1]
        if not last_segment:
            return []
        return [
            f"{last_segment}.go",
            f"{last_segment}/{last_segment}.go",
            f"{last_segment}/package.go",
        ]
    if language == "swift":
        return []
    return []


def _find_symbol_by_name(parsed: ParsedFile, name: str) -> dict[str, Any] | None:
    for symbol in [*parsed.function_symbols, *parsed.class_symbols]:
        if symbol.get("name") == name:
            return symbol
    return None


def _build_symbol_index(
    files: dict[str, ParsedFile],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for parsed in files.values():
        for symbol_type, symbols in (
            ("function", parsed.function_symbols),
            ("class", parsed.class_symbols),
        ):
            for symbol in symbols:
                name = symbol.get("name")
                if not name:
                    continue
                out.setdefault(name, []).append(
                    {
                        "path": parsed.path,
                        "language": parsed.language,
                        "symbol_type": symbol_type,
                        "symbol": symbol,
                    }
                )
    return out


def _make_reference_piece(
    kind: str, target: ParsedFile, symbol_type: str, symbol: dict[str, Any]
) -> dict[str, Any]:
    piece = {
        "kind": kind,
        "path": target.path,
        "language": target.language,
        "symbol_type": symbol_type,
        "name": symbol.get("name"),
        "code": symbol.get("code"),
        "line_range": symbol.get("line_range"),
    }
    if symbol_type == "function":
        piece["calls"] = symbol.get("calls", [])
        piece["imports_used"] = symbol.get("imports_used", [])
    return piece


def _resolve_import_reference(
    snapshot: RepositorySnapshot,
    importer: ParsedFile,
    symbol_name: str,
    *,
    depth: int = 0,
) -> list[dict[str, Any]]:
    if depth >= _MAX_REFERENCE_DEPTH:
        return []
    resolved: list[dict[str, Any]] = []
    for imp in importer.import_symbols:
        imported_names = imp.get("imported_names", [])
        namespace_aliases = imp.get("namespace_aliases", [])
        if symbol_name not in imported_names and symbol_name not in namespace_aliases:
            continue
        module_name = imp.get("module")
        module_candidates = _local_module_candidates(
            importer.path, module_name, importer.language
        )
        for candidate in module_candidates:
            target = snapshot.files.get(candidate)
            if not target:
                continue
            target_symbol_name = symbol_name
            symbol = _find_symbol_by_name(target, target_symbol_name)
            if symbol is not None:
                symbol_type = (
                    "function" if symbol in target.function_symbols else "class"
                )
                resolved.append(
                    _make_reference_piece(
                        "imported_reference", target, symbol_type, symbol
                    )
                )
                for imported in symbol.get("imports_used", []):
                    resolved.extend(
                        _resolve_import_reference(
                            snapshot, target, imported, depth=depth + 1
                        )
                    )
                return resolved
            for nested in target.import_symbols:
                if symbol_name in nested.get("imported_names", []):
                    resolved.append(
                        {
                            "kind": "import_bridge",
                            "path": target.path,
                            "language": target.language,
                            "code": nested.get("code"),
                            "line_range": nested.get("line_range"),
                            "name": symbol_name,
                        }
                    )
                    resolved.extend(
                        _resolve_import_reference(
                            snapshot, target, symbol_name, depth=depth + 1
                        )
                    )
                    return resolved
    return resolved


def _resolve_call_reference(
    snapshot: RepositorySnapshot,
    importer: ParsedFile,
    call_name: str,
    *,
    depth: int = 0,
) -> list[dict[str, Any]]:
    if depth >= _MAX_REFERENCE_DEPTH or not call_name:
        return []
    if "." in call_name:
        namespace, member = call_name.split(".", 1)
        from_import = _resolve_import_reference(
            snapshot, importer, namespace, depth=depth
        )
        if from_import:
            return from_import
        for imp in importer.import_symbols:
            if namespace not in imp.get("namespace_aliases", []):
                continue
            for candidate in _local_module_candidates(
                importer.path, imp.get("module"), importer.language
            ):
                target = snapshot.files.get(candidate)
                if not target:
                    continue
                symbol = _find_symbol_by_name(target, member)
                if symbol:
                    symbol_type = (
                        "function" if symbol in target.function_symbols else "class"
                    )
                    return [
                        _make_reference_piece(
                            "call_reference", target, symbol_type, symbol
                        )
                    ]
                dir_path = str(Path(candidate).parent).replace("\\", "/")
                package_files = [
                    parsed
                    for path, parsed in snapshot.files.items()
                    if str(Path(path).parent).replace("\\", "/") == dir_path
                ]
                for parsed in package_files:
                    symbol = _find_symbol_by_name(parsed, member)
                    if symbol:
                        symbol_type = (
                            "function" if symbol in parsed.function_symbols else "class"
                        )
                        return [
                            _make_reference_piece(
                                "call_reference", parsed, symbol_type, symbol
                            )
                        ]
    for candidate in snapshot.symbol_index.get(call_name, []):
        if candidate["path"] == importer.path:
            continue
        return [
            _make_reference_piece(
                "call_reference",
                snapshot.files[candidate["path"]],
                candidate["symbol_type"],
                candidate["symbol"],
            )
        ]
    return []


def _snapshot_from_code(language: str | None, code: str) -> dict[str, Any] | None:
    if not language or not code.strip():
        return None
    parser = _get_tree_sitter_parser(language)
    if not parser:
        return None
    raw = code.encode("utf-8")
    try:
        tree = parser.parse(raw)
    except Exception:
        return None
    return _build_symbol_snapshot(_extract_symbols(language, raw, tree))


def _parse_file(path: Path, repo_dir: Path) -> ParsedFile:
    rel_path = path.relative_to(repo_dir).as_posix()
    language = detect_language(rel_path)
    try:
        raw = path.read_bytes()
    except OSError:
        return ParsedFile(rel_path, language, None, None, None, {}, [], [], [], [])

    if len(raw) > _MAX_FILE_SNAPSHOT_BYTES:
        return ParsedFile(rel_path, language, None, None, None, {}, [], [], [], [])

    text = raw.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    parser = _get_tree_sitter_parser(language) if language else None
    tree = parser.parse(raw) if parser else None
    symbols = (
        _extract_symbols(language, raw, tree)
        if tree
        else {"functions": [], "classes": [], "imports": [], "calls": []}
    )
    return ParsedFile(
        rel_path,
        language,
        text,
        lines,
        tree,
        _build_symbol_snapshot(symbols),
        symbols["functions"],
        symbols["classes"],
        symbols["imports"],
        symbols["calls"],
    )


def build_repository_snapshot(repo_dir: Path) -> RepositorySnapshot:
    files: dict[str, ParsedFile] = {}
    inventory: list[dict[str, Any]] = []
    logger.info("Building repository snapshot for %s", repo_dir)

    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        lower_path = path.name.lower()
        if "lock" in lower_path:
            continue
        parsed = _parse_file(path, repo_dir)
        files[parsed.path] = parsed
        inventory.append(
            {
                "path": parsed.path,
                "language": parsed.language,
                "line_count": len(parsed.lines or []),
                "symbols": parsed.symbol_snapshot,
            }
        )

    logger.info("Building symbol index for %s", repo_dir)
    snapshot_path = repo_dir / ".greagent-review-snapshot.json"
    symbol_index = _build_symbol_index(files)
    logger.info("Symbol index built for %s", repo_dir)
    snapshot_path.write_text(
        json.dumps(
            {
                "repo_dir": str(repo_dir),
                "files": inventory,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Repository snapshot built for %s", repo_dir)
    return RepositorySnapshot(
        repo_dir=repo_dir,
        snapshot_path=snapshot_path,
        files=files,
        file_inventory=inventory,
        symbol_index=symbol_index,
    )


def _parse_patch_header(raw_line: str) -> tuple[int, int, int, int] | None:
    if not raw_line.startswith("@@ -"):
        return None
    try:
        middle = raw_line[4:]
        old_part, rest = middle.split(" +", 1)
        new_part = rest.split(" @@", 1)[0]

        def parse_range(part: str) -> tuple[int, int]:
            if "," in part:
                start_s, count_s = part.split(",", 1)
                return int(start_s), int(count_s)
            return int(part), 1

        old_start, old_count = parse_range(old_part)
        new_start, new_count = parse_range(new_part)
        return old_start, old_count, new_start, new_count
    except (ValueError, IndexError):
        return None


def parse_patch(patch: str) -> list[DiffHunk]:
    if not patch:
        return []

    hunks: list[DiffHunk] = []
    current: DiffHunk | None = None
    old_line = 0
    new_line = 0

    for raw_line in patch.splitlines():
        header = _parse_patch_header(raw_line)
        if header is not None:
            if current is not None:
                hunks.append(current)
            old_start, old_count, new_start, new_count = header
            current = DiffHunk(
                header=raw_line,
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            old_line = old_start
            new_line = new_start
            continue

        if current is None or raw_line.startswith("\\"):
            continue

        prefix = raw_line[:1]
        text = raw_line[1:]
        if prefix == " ":
            current.lines.append(DiffLine("context", old_line, new_line, text))
            old_line += 1
            new_line += 1
        elif prefix == "+":
            current.lines.append(DiffLine("add", None, new_line, text))
            new_line += 1
        elif prefix == "-":
            current.lines.append(DiffLine("del", old_line, None, text))
            old_line += 1

    if current is not None:
        hunks.append(current)
    return hunks


def fetch_pr_file_diffs(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
) -> list[PullRequestFileDiff]:
    logger.info("Fetching PR file diffs for %s", pr_number)
    files = list_pr_review_files(owner, repo, pr_number, token)
    out: list[PullRequestFileDiff] = []
    for item in files:
        path = str(item.get("filename") or "")
        patch = str(item.get("patch") or "")
        out.append(
            PullRequestFileDiff(
                path=path,
                status=str(item.get("status") or "modified"),
                patch=patch,
                previous_filename=item.get("previous_filename"),
                language=detect_language(path),
                hunks=parse_patch(patch),
            )
        )
    logger.info("PR file diffs fetched for %s", pr_number)
    return out


def _symbol_for_line(
    parsed: ParsedFile, line_number: int
) -> tuple[str, dict[str, Any]] | None:
    for symbol in parsed.function_symbols:
        start_line, end_line = symbol.get("line_range", [0, 0])
        if start_line <= line_number <= end_line:
            return "function", symbol
    for symbol in parsed.class_symbols:
        start_line, end_line = symbol.get("line_range", [0, 0])
        if start_line <= line_number <= end_line:
            return "class", symbol
    return None


def _context_piece_from_symbol(
    *,
    kind: str,
    path: str,
    language: str | None,
    symbol_type: str,
    symbol: dict[str, Any],
    focus_line: int | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": kind,
        "path": path,
        "language": language,
        "symbol_type": symbol_type,
        "name": symbol.get("name"),
        "line_range": symbol.get("line_range"),
        "code": symbol.get("code"),
    }
    if focus_line is not None:
        payload["focus_line"] = focus_line
    if symbol_type == "function":
        payload["calls"] = symbol.get("calls", [])
        payload["imports_used"] = symbol.get("imports_used", [])
    return payload


def collect_relevant_context(
    snapshot: RepositorySnapshot,
    file_diffs: list[PullRequestFileDiff],
) -> list[dict[str, Any]]:
    pieces: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str | None]] = set()

    def add_piece(piece: dict[str, Any]) -> None:
        key = (
            piece.get("path", ""),
            piece.get("kind", ""),
            piece.get("name"),
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        pieces.append(piece)

    for file_diff in file_diffs:
        parsed = snapshot.files.get(file_diff.path)
        for hunk in file_diff.hunks:
            new_code = hunk.new_code()
            old_code = hunk.old_code()
            add_piece(
                {
                    "kind": "diff_new",
                    "path": file_diff.path,
                    "language": file_diff.language,
                    "hunk_header": hunk.header,
                    "code": new_code,
                    "symbols": _snapshot_from_code(file_diff.language, new_code),
                }
            )
            if old_code != new_code:
                add_piece(
                    {
                        "kind": "diff_old",
                        "path": file_diff.path,
                        "language": file_diff.language,
                        "hunk_header": hunk.header,
                        "code": old_code,
                        "symbols": _snapshot_from_code(file_diff.language, old_code),
                    }
                )

            if not parsed or not parsed.lines:
                continue
            for line_number in hunk.added_new_lines[:8]:
                match = _symbol_for_line(parsed, line_number)
                if not match:
                    continue
                symbol_type, symbol = match
                add_piece(
                    _context_piece_from_symbol(
                        kind="repo_context",
                        path=file_diff.path,
                        language=parsed.language,
                        symbol_type=symbol_type,
                        symbol=symbol,
                        focus_line=line_number,
                    )
                )
                if symbol_type == "function":
                    for imported_name in symbol.get("imports_used", []):
                        for reference in _resolve_import_reference(
                            snapshot,
                            parsed,
                            imported_name,
                        ):
                            add_piece(reference)
                    for call_name in symbol.get("calls", []):
                        for reference in _resolve_call_reference(
                            snapshot,
                            parsed,
                            call_name,
                        ):
                            add_piece(reference)
    return pieces


def _truncate_comment_payload(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": comment.get("path"),
        "line": comment.get("line"),
        "side": comment.get("side"),
        "body": str(comment.get("body") or "")[:500],
        "user": ((comment.get("user") or {}).get("login")),
    }


def fetch_previous_comments(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
) -> dict[str, list[dict[str, Any]]]:
    issue_comments = list_pr_issue_comments(owner, repo, pr_number, token)
    review_comments = list_pr_review_comments(owner, repo, pr_number, token)
    return {
        "issue_comments": [
            {
                "user": (c.get("user") or {}).get("login"),
                "body": str(c.get("body") or "")[:800],
            }
            for c in issue_comments[-_MAX_PREVIOUS_COMMENTS:]
        ],
        "review_comments": [
            _truncate_comment_payload(c)
            for c in review_comments[-_MAX_PREVIOUS_COMMENTS:]
        ],
    }


def _llm_context_payload(
    relevant_context: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep only minimal context for the LLM: code plus lightweight file anchors.
    Drop symbol metadata (names, ranges, calls, imports, nested symbol trees).
    """
    payload: list[dict[str, Any]] = []
    for piece in relevant_context:
        code = str(piece.get("code") or "").strip()
        if not code:
            continue
        payload.append(
            {
                "kind": piece.get("kind"),
                "path": piece.get("path"),
                "hunk_header": piece.get("hunk_header"),
                "code": code,
            }
        )
    return payload


def _extract_json_payload(text: str) -> dict[str, Any]:
    payload = text.strip()
    if payload.startswith("```"):
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            payload = payload[start : end + 1]
    return json.loads(payload)


def build_review_prompt(
    pr: PROpenedForReview,
    file_diffs: list[PullRequestFileDiff],
    relevant_context: list[dict[str, Any]],
    previous_comments: dict[str, list[dict[str, Any]]],
) -> str:
    diff_payload = [
        {
            "path": file_diff.path,
            "status": file_diff.status,
            "language": file_diff.language,
            "commentable_right_lines": sorted(file_diff.right_commentable_lines),
            "commentable_left_lines": sorted(file_diff.left_commentable_lines),
            "patch": file_diff.patch,
        }
        for file_diff in file_diffs
    ]
    llm_context_payload = _llm_context_payload(relevant_context)
    return f"""
You are reviewing GitHub pull request #{pr.pr_number} for repository {pr.full_name}.

Rules:
- Review only the reviewer agent path; do not suggest code unrelated to this diff.
- Prefer inline comments only for actionable, concrete issues.
- Do not repeat existing comments unless the issue is still unresolved and materially important.
- Inline comment lines must match the provided commentable lines for the file and side.
- Use REQUEST_CHANGES only for real correctness, security, or maintainability issues that should block merge.
- Use APPROVE when there are no substantive findings. Use COMMENT for non-blocking feedback.

PR title: {pr.pr_title}
PR body:
{pr.pr_body or "(No description provided)"}

Base branch: {pr.base_branch}
Head branch: {pr.head_branch}

Changed file diffs:
{json.dumps(diff_payload, indent=2)}

Relevant extracted code context:
{json.dumps(llm_context_payload, indent=2)}

Existing PR comments:
{json.dumps(previous_comments, indent=2)}
""".strip()


def generate_review_decision(
    pr: PROpenedForReview,
    file_diffs: list[PullRequestFileDiff],
    relevant_context: list[dict[str, Any]],
    previous_comments: dict[str, list[dict[str, Any]]],
) -> ReviewDecision:
    prompt = build_review_prompt(
        pr,
        file_diffs,
        relevant_context,
        previous_comments,
    )
    agent = create_agent(
        model=get_github_deep_agent_llm(),
        tools=[],
        response_format=ToolStrategy(ReviewDecision),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    structured = result.get("structured_response")
    if structured is None:
        raise RuntimeError("Missing structured_response from reviewer output")
    if isinstance(structured, ReviewDecision):
        return structured
    return ReviewDecision.model_validate(structured)


def _comment_is_valid(
    comment: ReviewInlineComment, file_diff: PullRequestFileDiff
) -> bool:
    allowed = (
        file_diff.right_commentable_lines
        if comment.side == "RIGHT"
        else file_diff.left_commentable_lines
    )
    if comment.line not in allowed:
        return False
    if comment.start_line is not None and comment.start_line not in allowed:
        return False
    if comment.start_line is not None and comment.start_line > comment.line:
        return False
    if comment.start_side is not None and comment.start_side != comment.side:
        return False
    return True


def publish_review(
    pr: PROpenedForReview,
    token: str,
    decision: ReviewDecision,
    file_diffs: list[PullRequestFileDiff],
) -> None:
    diffs_by_path = {file_diff.path: file_diff for file_diff in file_diffs}
    for comment in decision.inline_comments:
        file_diff = diffs_by_path.get(comment.path)
        if not file_diff:
            logger.warning("Skipping inline comment for unknown path %s", comment.path)
            continue
        if not _comment_is_valid(comment, file_diff):
            logger.warning(
                "Skipping inline comment with invalid anchor path=%s line=%s side=%s",
                comment.path,
                comment.line,
                comment.side,
            )
            continue
        create_pr_review_comment(
            owner=pr.owner,
            repo=pr.repo_name,
            pr_number=pr.pr_number,
            token=token,
            body=comment.body,
            commit_id=pr.head_sha,
            path=comment.path,
            line=comment.line,
            side=comment.side,
            start_line=comment.start_line,
            start_side=comment.start_side,
        )

    comment_on_pr(
        owner=pr.owner,
        repo=pr.repo_name,
        pr_number=pr.pr_number,
        token=token,
        body=decision.pr_comment_body,
    )
    submit_pr_review(
        owner=pr.owner,
        repo=pr.repo_name,
        pr_number=pr.pr_number,
        token=token,
        event=decision.review_event,
        body=decision.review_body,
    )
