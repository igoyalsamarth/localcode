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
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Collection, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

from constants import AGENT_LLM_PROVIDER, get_agent_model_name
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

# Compact JSON in LLM user messages (token-efficient; same data as pretty-printed).
_REVIEW_USER_MESSAGE_JSON_KWARGS: dict[str, Any] = {
    "separators": (",", ":"),
    "ensure_ascii": False,
}

_MAX_PREVIOUS_COMMENTS = 25
_MAX_FILE_SNAPSHOT_BYTES = 250_000
_MAX_REFERENCE_DEPTH = 3
# Cap tree-sitter work when snapshotting by PR file list + import expansion.
_MAX_SNAPSHOT_PARSE_FILES = 800

_REPO_SNAPSHOT_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        "bower_components",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".tox",
        "dist",
        "build",
        ".next",
        "out",
        "target",
        "htmlcov",
        ".git",
        "Pods",
        "DerivedData",
    }
)

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
    def modified_new_lines(self) -> list[int]:
        """Return all new lines that are part of modifications (adds + context around changes)."""
        return [
            line.new_line
            for line in self.lines
            if line.kind in ("context", "add") and line.new_line
        ]

    @property
    def new_file_lines_for_repo_context(self) -> list[int]:
        """
        New-file line numbers that should drive symbol / repo context extraction.

        Unlike :meth:`modified_new_lines`, this **excludes** pure context lines that
        only appear in the hunk to show surrounding unchanged code. Those lines often
        map to large enclosing scopes in the AST and pull in unrelated code.

        Includes: every added line, and the first new-file line that follows each
        deletion (so delete-only hunks can still resolve symbols on the new side).
        """
        out: set[int] = set()
        for i, line in enumerate(self.lines):
            if line.kind == "add" and line.new_line is not None:
                out.add(line.new_line)
            if line.kind != "del":
                continue
            for j in range(i + 1, len(self.lines)):
                n = self.lines[j]
                if n.new_line is not None and n.kind in ("add", "context"):
                    out.add(n.new_line)
                    break
        return sorted(out)

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


InlineCommentSeverity = Literal[
    "nitpick",
    "minor_bug",
    "major_bug",
    "blocking",
    "security",
    "other",
]


class ReviewInlineComment(BaseModel):
    path: str = Field(..., description="The file path of the inline comment.")
    line: int = Field(
        ...,
        description="The line number on which to comment on the specified side.",
    )
    severity: InlineCommentSeverity = Field(
        ...,
        description=(
            "Required classification: ``nitpick`` (style/polish), ``minor_bug`` (real issue, "
            "usually non-blocking), ``major_bug`` (serious correctness/reliability), ``blocking`` "
            "(should block merge), ``security`` (security impact), ``other`` (maintainability, "
            "docs, or anything that does not fit the above). Align ``review_event``: use "
            "REQUEST_CHANGES when any inline is ``blocking``, ``major_bug``, or ``security`` "
            "that should stop merge."
        ),
    )
    body: str = Field(
        ...,
        description=(
            "Markdown: one distinct actionable issue—correctness, security, user-visible "
            "behavior, reliability, or meaningful maintainability tied to this diff. Explain "
            "the risk and a concrete fix when practical. Skip pure style or naming preferences. "
            "Do **not** start with ``Line N:``, ``L42:``, or similar—the inline is already "
            "anchored on GitHub; use the structured ``line`` field only. Do **not** prefix "
            "with severity text; severity is a separate field and is prepended when posting."
        ),
    )
    side: Literal["RIGHT", "LEFT"] = Field(
        "RIGHT",
        description=(
            "Always 'RIGHT' here: anchor to head branch lines listed in ``commentable_right_lines``."
        ),
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
    summary: str = Field(
        ...,
        description=(
            "Very short recap (1–3 sentences): verdict and scale of findings. Do not re-list "
            "issues that are already explained in ``inline_comments``—reference that you left "
            "inlines instead of repeating details."
        ),
    )
    review_event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = "COMMENT"
    review_body: str = Field(
        ...,
        description=(
            "Markdown on the **submitted PR review** (approve/request-changes/comment). "
            "**Verdict-first:** headline + at most brief bullets for themes or merge posture only. "
            "Put every concrete, anchorable finding in ``inline_comments`` with full detail there—"
            "do **not** repeat the same explanation here (avoids duplicate text across review vs "
            "inlines). You may say e.g. “See inline comments on …” or “N findings inlines below.”"
        ),
    )
    pr_comment_body: str = Field(
        ...,
        description=(
            "Markdown for the **PR conversation (issue) comment**. Keep it **minimal and non-"
            "duplicative**: thank-you, one-line summary, or merge nudge—**not** a second copy "
            "of inline findings or the same bullets as ``review_body``. If nothing to add beyond "
            "the review + inlines, a single short sentence is enough."
        ),
    )
    inline_comments: list[ReviewInlineComment] = Field(
        default_factory=list,
        description=(
            "Primary place for **specific** findings: one anchored inline per distinct issue "
            "you can tie to ``commentable_right_lines``. Prefer many precise inlines over few "
            "generic summary bullets. Empty only if there are no actionable findings."
        ),
    )


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


def _extract_decorators(node: Any, source: bytes) -> list[str]:
    """Extract decorators from a function/class node (Python specific)."""
    decorators = []
    # In tree-sitter Python, decorators are siblings that come before the function
    parent = getattr(node, "parent", None)
    if parent is None:
        return decorators

    children = getattr(parent, "named_children", [])
    for i, child in enumerate(children):
        if child == node:
            # Look backwards for decorator nodes
            for j in range(i - 1, -1, -1):
                child_type = getattr(children[j], "type", None)
                if child_type == "decorator":
                    decorator_text = _node_text(source, children[j]).strip()
                    decorators.insert(0, decorator_text)
                elif child_type not in ("comment", "string"):
                    # Stop if we hit something that's not a decorator or comment
                    break
            break

    return decorators


def _extract_function_symbol(
    language: str | None, node: Any, source: bytes
) -> dict[str, Any]:
    start_line, end_line = _line_span(node)
    name = _extract_symbol_name(language, node, source)
    code = _node_text(source, node).strip()
    identifiers = _dedupe_keep_order(_collect_identifier_texts(node, source))

    # Extract decorators (mainly for Python)
    decorators = []
    if language == "python":
        decorators = _extract_decorators(node, source)

    symbol = {
        "name": name,
        "code": code,
        "line_range": [start_line, end_line],
        "calls": [],
        "imports_used": [],
        "identifiers": identifiers,
        "decorators": decorators,
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
                "decorators": symbol.get("decorators", []),
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


def _snapshot_path_is_skipped(rel_posix: str) -> bool:
    return any(part in _REPO_SNAPSHOT_SKIP_DIR_NAMES for part in rel_posix.split("/"))


def _append_inventory_entry(
    inventory: list[dict[str, Any]], parsed: ParsedFile
) -> None:
    inventory.append(
        {
            "path": parsed.path,
            "language": parsed.language,
            "line_count": len(parsed.lines or []),
            "symbols": parsed.symbol_snapshot,
        }
    )


def _build_snapshot_from_focus_paths(
    repo_dir: Path,
    focus_paths: Collection[str],
    *,
    max_parsed_files: int,
) -> tuple[dict[str, ParsedFile], list[dict[str, Any]]]:
    """
    Tree-parse only PR (or seed) paths, then expand across local imports.

    Avoids scanning huge monorepos (e.g. tens of thousands of tree-sitter parses).
    """
    files: dict[str, ParsedFile] = {}
    inventory: list[dict[str, Any]] = []
    q: deque[str] = deque()
    seen: set[str] = set()
    for raw in focus_paths:
        rel = raw.replace("\\", "/").lstrip("/")
        if rel and rel not in seen:
            seen.add(rel)
            q.append(rel)

    parsed_count = 0
    while q and len(files) < max_parsed_files:
        rel = q.popleft()
        if _snapshot_path_is_skipped(rel):
            continue
        path = repo_dir / rel
        if not path.is_file():
            continue
        lower_path = path.name.lower()
        if "lock" in lower_path:
            continue
        parsed = _parse_file(path, repo_dir)
        files[parsed.path] = parsed
        _append_inventory_entry(inventory, parsed)
        parsed_count += 1
        if parsed_count % 50 == 0:
            logger.info(
                "Snapshot parse progress: %s files (focus mode, repo=%s)",
                parsed_count,
                repo_dir,
            )
        for imp in parsed.import_symbols:
            module = imp.get("module")
            if not isinstance(module, str) or not module.strip():
                continue
            for cand in _local_module_candidates(parsed.path, module, parsed.language):
                if cand in seen or _snapshot_path_is_skipped(cand):
                    continue
                seen.add(cand)
                q.append(cand)

    if len(files) >= max_parsed_files and q:
        logger.warning(
            "Snapshot parse cap reached (%s files); remaining import queue not drained (repo=%s)",
            max_parsed_files,
            repo_dir,
        )
    return files, inventory


def build_repository_snapshot(
    repo_dir: Path,
    focus_paths: Collection[str] | None = None,
    *,
    max_parsed_files: int = _MAX_SNAPSHOT_PARSE_FILES,
) -> RepositorySnapshot:
    files: dict[str, ParsedFile] = {}
    inventory: list[dict[str, Any]] = []
    if focus_paths is not None and len(focus_paths) > 0:
        logger.info(
            "Building repository snapshot (PR-focused, up to %s files) for %s",
            max_parsed_files,
            repo_dir,
        )
        files, inventory = _build_snapshot_from_focus_paths(
            repo_dir, focus_paths, max_parsed_files=max_parsed_files
        )
    else:
        if focus_paths is not None:
            logger.info(
                "Building repository snapshot (full scan, no PR paths) for %s",
                repo_dir,
            )
        else:
            logger.info("Building repository snapshot (full scan) for %s", repo_dir)

        parsed_count = 0
        for path in sorted(repo_dir.rglob("*")):
            if not path.is_file():
                continue
            if ".git" in path.parts:
                continue
            rel = path.relative_to(repo_dir).as_posix()
            if _snapshot_path_is_skipped(rel):
                continue
            lower_path = path.name.lower()
            if "lock" in lower_path:
                continue
            parsed = _parse_file(path, repo_dir)
            files[parsed.path] = parsed
            _append_inventory_entry(inventory, parsed)
            parsed_count += 1
            if parsed_count % 200 == 0:
                logger.info(
                    "Snapshot parse progress: %s files (full scan, repo=%s)",
                    parsed_count,
                    repo_dir,
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


def _is_test_file(path: str) -> bool:
    """Check if a file is a test file based on naming conventions."""
    path_lower = path.lower()
    path_parts = Path(path).parts

    # Check file name patterns
    filename = Path(path).name.lower()
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith("_test.js")
    ):
        return True

    # Check if in test directory
    if "test" in path_parts or "tests" in path_parts or "__tests__" in path_parts:
        return True

    # Check spec files (JavaScript/TypeScript)
    if filename.endswith(".spec.ts") or filename.endswith(".spec.js"):
        return True

    return False


def _extract_test_context(
    snapshot: RepositorySnapshot,
    parsed: ParsedFile,
    modified_function_names: set[str],
) -> list[dict[str, Any]]:
    """Extract test-specific context: fixtures, decorators, and conftest."""
    context = []

    # Extract pytest fixtures defined in the file
    for func in parsed.function_symbols:
        decorators = func.get("decorators", [])
        func_name = func.get("name", "")

        # Skip if this is one of the modified functions (will be added separately)
        if func_name in modified_function_names:
            continue

        # Look for pytest fixtures
        is_fixture = any(
            "pytest.fixture" in dec or "@fixture" in dec for dec in decorators
        )
        if is_fixture:
            context.append(
                {
                    "kind": "pytest_fixture",
                    "path": parsed.path,
                    "language": parsed.language,
                    "name": func_name,
                    "decorators": decorators,
                    "code": func.get("code", "")[:1500],  # Truncate to save tokens
                    "line_range": func.get("line_range"),
                }
            )

    # Extract module-level imports to show mock.patch and other test utilities
    if parsed.import_symbols:
        imports_code = "\n".join(
            imp.get("code", "") for imp in parsed.import_symbols[:20]
        )
        if imports_code.strip():
            context.append(
                {
                    "kind": "test_imports",
                    "path": parsed.path,
                    "language": parsed.language,
                    "code": imports_code,
                }
            )

    # Look for conftest.py in the same directory
    conftest_path = Path(parsed.path).parent / "conftest.py"
    conftest_str = str(conftest_path)
    if conftest_str in snapshot.files:
        conftest_parsed = snapshot.files[conftest_str]
        # Extract fixtures from conftest
        for func in conftest_parsed.function_symbols[:5]:  # Limit to first 5
            decorators = func.get("decorators", [])
            is_fixture = any(
                "pytest.fixture" in dec or "@fixture" in dec for dec in decorators
            )
            if is_fixture:
                context.append(
                    {
                        "kind": "conftest_fixture",
                        "path": conftest_str,
                        "language": conftest_parsed.language,
                        "name": func.get("name"),
                        "decorators": decorators,
                        "code": func.get("code", "")[:1000],
                        "line_range": func.get("line_range"),
                    }
                )

    return context


def _line_in_any_import_block(parsed: ParsedFile, line_number: int) -> bool:
    for imp in parsed.import_symbols:
        lr = imp.get("line_range") or [0, 0]
        if (
            isinstance(lr, list)
            and len(lr) >= 2
            and int(lr[0]) <= line_number <= int(lr[1])
        ):
            return True
    return False


def _all_triggers_are_import_only(
    parsed: ParsedFile, line_numbers: Collection[int]
) -> bool:
    """True when every line is inside a tree-sitter import block (imports-only hunk)."""
    if not line_numbers:
        return False
    return all(_line_in_any_import_block(parsed, ln) for ln in line_numbers)


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
        # Include decorators if present (important for test files)
        decorators = symbol.get("decorators", [])
        if decorators:
            payload["decorators"] = decorators
    return payload


def build_review_file_blocks(
    snapshot: RepositorySnapshot,
    file_diffs: list[PullRequestFileDiff],
) -> list[dict[str, Any]]:
    """
    One JSON-serializable block per file: each hunk has the two-sided hunk text,
    per-hunk commentable line lists, and ``extra_context`` (repo/imports/calls) for
    that hunk. The hunk text is not repeated under ``kind: diff_new``/``diff_old``;
    those go only in ``right_code`` and optional ``left_code`` to match the final
    prompt the model sees.
    """
    out: list[dict[str, Any]] = []
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
        extra_by_hunk.append(piece)

    for file_diff in file_diffs:
        parsed = snapshot.files.get(file_diff.path)
        is_test = _is_test_file(file_diff.path)
        modified_function_names: set[str] = set()
        hunks_serialized: list[dict[str, Any]] = []

        for hunk in file_diff.hunks:
            extra_by_hunk: list[dict[str, Any]] = []
            new_code = hunk.new_code()
            old_code = hunk.old_code()

            if parsed and parsed.lines:
                symbol_triggers = set(hunk.new_file_lines_for_repo_context)
                skip_class_and_function_repo = _all_triggers_are_import_only(
                    parsed, symbol_triggers
                )

                if not skip_class_and_function_repo and symbol_triggers:
                    modified_symbols: set[tuple[str, int]] = set()
                    for line_number in symbol_triggers:
                        match = _symbol_for_line(parsed, line_number)
                        if not match:
                            continue
                        symbol_type, symbol = match
                        try:
                            symbol_index = (
                                parsed.function_symbols.index(symbol)
                                if symbol_type == "function"
                                and symbol in parsed.function_symbols
                                else parsed.class_symbols.index(symbol)
                            )
                        except ValueError:
                            continue
                        modified_symbols.add((symbol_type, symbol_index))

                    for symbol_type, symbol_index in list(modified_symbols)[:12]:
                        if symbol_type == "function":
                            symbol = parsed.function_symbols[symbol_index]
                        else:
                            symbol = parsed.class_symbols[symbol_index]

                        modified_function_names.add(str(symbol.get("name") or ""))

                        symbol_start, symbol_end = symbol.get("line_range", [0, 0])
                        focus_line = None
                        for line_num in sorted(symbol_triggers):
                            if symbol_start <= line_num <= symbol_end:
                                focus_line = line_num
                                break

                        add_piece(
                            _context_piece_from_symbol(
                                kind="repo_context",
                                path=file_diff.path,
                                language=parsed.language,
                                symbol_type=symbol_type,
                                symbol=symbol,
                                focus_line=focus_line,
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

            llm_hunk: dict[str, Any] = {
                "hunk_header": hunk.header,
                "right_code": new_code,
                "commentable_right_lines": sorted(
                    {ln for ln in hunk.right_commentable_lines if ln is not None}
                ),
                "extra_context": _llm_context_payload(extra_by_hunk),
            }
            if old_code != new_code:
                llm_hunk["left_code"] = old_code
            hunks_serialized.append(llm_hunk)

        file_block: dict[str, Any] = {
            "path": file_diff.path,
            "status": file_diff.status,
            "language": file_diff.language,
            "hunks": hunks_serialized,
        }
        if is_test and parsed:
            test_context = _extract_test_context(
                snapshot, parsed, modified_function_names
            )
            as_llm = _llm_context_payload(test_context)
            if as_llm:
                file_block["file_level_context"] = as_llm
        out.append(file_block)
    return out


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
    Keep decorators as they are critical for understanding test behavior.
    """
    payload: list[dict[str, Any]] = []
    for piece in relevant_context:
        code = str(piece.get("code") or "").strip()
        if not code:
            continue

        llm_piece = {
            "kind": piece.get("kind"),
            "path": piece.get("path"),
            "hunk_header": piece.get("hunk_header"),
            "code": code,
        }

        # Keep decorators for test files (critical context)
        decorators = piece.get("decorators")
        if decorators:
            llm_piece["decorators"] = decorators

        # Keep name for better context understanding
        name = piece.get("name")
        if name:
            llm_piece["name"] = name

        payload.append(llm_piece)

    return payload


def _extract_json_payload(text: str) -> dict[str, Any]:
    payload = text.strip()
    if payload.startswith("```"):
        start = payload.find("{")
        end = payload.rfind("}")
        if start != -1 and end != -1 and end > start:
            payload = payload[start : end + 1]
    return json.loads(payload)


# Stable instructions: paired with a user message that contains the specific PR and diffs.
_GITHUB_REVIEW_SYSTEM_MESSAGE = """
You are a code reviewer for GitHub pull requests. The user message contains one PR: repository, number, title, body, base/head branches, changed file blocks (JSON), and prior comments (JSON). Produce the structured response required by the tool (summary, review_event, review_body, pr_comment_body, inline_comments).

Output fields (GitHub mapping) — **no duplicate findings across channels:**
- **Put the substantive finding on the inline** whenever it can be anchored to ``commentable_right_lines``. Full explanation, risk, and fix belong in the inline ``body``.
- ``review_body``: **Verdict + posture only** (approve / request changes / commented with why). Optional ultra-short theme (“mostly small nits”, “one blocking auth issue”)—**do not** re-copy the same paragraphs or bullet points that already appear in ``inline_comments``. Prefer “See inlines on ``path``” over repeating them.
- ``pr_comment_body``: **Minimal** (one or two sentences): optional thank-you, merge hint, or meta note. **Must not** restate individual findings that are already in inlines or duplicate ``review_body``.
- ``summary``: 1–3 sentences max; no issue-by-issue rehash if inlines cover it.

**Prefer more inlines, less generic prose:** If you see several distinct issues on the diff, use **several inline comments** (each one specific). Avoid long generic walls of text in ``review_body`` / ``pr_comment_body`` that mirror those points.

Scope:
- Focus on what this PR changes: each file entry has ``hunks``; each hunk has ``right_code`` (and ``left_code`` when the base differed), optional ``extra_context``, and optional ``file_level_context`` (tests). Do not suggest unrelated refactors of untouched code.
- **Diff pass:** Walk ``right_code`` against ``left_code`` when present: treat every added or materially changed line as a mini code review—correctness, API misuse, and “would this behave differently in another environment (OS, runtime, locale)?”. Then use ``extra_context`` / ``file_level_context`` for call sites, types, and tests.

First review the diff purely, before using the context to guide your review.
Take a first pass at the diff, and raise issues around categories:
- Shell and tooling safety (injection, word-splitting, flags or syntax that differ across OS or tool implementations)
- Validation misuse
- Access control bugs
- Language semantics: truthiness, reference vs value equality (including time/wrapper types where the language compares identity, not instant)

Inline comments (primary output for findings):
- **Default:** Every distinct issue you would mention in a review should appear as an **inline** if it can be anchored. Do not “save” findings for ``review_body`` only—readers and evals expect specifics on the diff.
- One distinct issue per inline; anchor to the best line (or short range) using only
  ``commentable_right_lines`` in the *same* hunk as the change, with ``side`` ``RIGHT`` (``right_code`` / head branch). Do not use ``LEFT``/base side for inline review comments.
- In ``body``, **do not** write ``Line 28:`` / ``L28:`` / line-number prefixes—the review UI already shows which line the comment is on. Put line numbers only in the structured ``line`` field.
- **Every inline must set ``severity``** (required): one of ``nitpick``, ``minor_bug``, ``major_bug``, ``blocking``, ``security``, ``other``. Choose the best fit; use ``other`` instead of omitting. Use ``blocking`` / ``major_bug`` / ``security`` for issues that justify REQUEST_CHANGES when merge should stop; ``minor_bug`` / ``nitpick`` / ``other`` for non-blocking feedback. Still spell out impact in ``body`` (do not duplicate the severity label in prose—the post step prepends it for GitHub).
- Each inline should be actionable and **specific** (not “consider testing” with no tie to the changed lines). Say what can go wrong and how to fix when clear.
- Prefer real defects (bugs, security, wrong behavior, reliability, contract/API misuse) grounded in the diff or supplied context. Avoid generic praise, vague worries, and pure style or naming preferences.
- **Only if** something cannot be tied to any ``commentable_right_lines`` may you mention it briefly in ``review_body`` alone (rare); never paste the same text in both an inline and a summary.

Coverage:
- Before finishing, skim changed logic for common problems you can tie to this diff: validation/auth gaps, boundary/off-by-one mistakes, async/races or missing ``await``, error handling that hides failures, resource leaks, injection or unsafe deserialization, incorrect API usage, environment/portability of scripts and one-liners, and similar issues. Include medium-severity problems when they are plausible, not only catastrophic cases.

Test-specific guidance:
- For test files, pay attention to ``decorators`` field showing @mock.patch, @pytest.fixture, etc. These affect test behavior.
- Check if mocked/patched functions are actually being used correctly in the test body.
- Look for issues like: monkeypatched time.sleep that makes actual sleep calls no-ops, isinstance checks that fail due to multiprocessing contexts (spawn/fork create subclass instances), fixed sleeps vs condition waits for reliability.

Review outcome:
- Do not repeat existing comments unless the issue still applies and matters.
- Use REQUEST_CHANGES only when merge should be blocked (correctness, security, serious defects); align with ``severity`` on inlines (typically ``blocking``, ``major_bug``, or material ``security``).
- Use APPROVE when there are no material findings; use COMMENT for non-blocking feedback.
""".strip()


def build_review_user_message(
    pr: PROpenedForReview,
    review_file_blocks: list[dict[str, Any]],
    previous_comments: dict[str, list[dict[str, Any]]],
) -> str:
    """PR-specific input: metadata plus JSON for changed files and prior comments."""
    return f"""# Pull request to review

- **Repository:** {pr.full_name}
- **PR number:** {pr.pr_number}
- **Base branch:** {pr.base_branch}
- **Head branch:** {pr.head_branch}

## Title
{pr.pr_title}

## Description
{pr.pr_body or "(No description provided)"}

## Changed files
Per hunk: diff text (``right_code`` / optional ``left_code``), ``commentable_right_lines``, and ``extra_context`` (no full-file patch duplicate). Optional per-file ``file_level_context`` for tests. JSON below is minified to save tokens.

```json
{json.dumps(review_file_blocks, **_REVIEW_USER_MESSAGE_JSON_KWARGS)}
```

## Existing PR comments
```json
{json.dumps(previous_comments, **_REVIEW_USER_MESSAGE_JSON_KWARGS)}
```
""".strip()


def generate_review_decision(
    pr: PROpenedForReview,
    review_file_blocks: list[dict[str, Any]],
    previous_comments: dict[str, list[dict[str, Any]]],
) -> ReviewDecision:
    user_message = build_review_user_message(
        pr,
        review_file_blocks,
        previous_comments,
    )
    agent = create_agent(
        model=f"{AGENT_LLM_PROVIDER}:{get_agent_model_name()}",
        system_prompt=_GITHUB_REVIEW_SYSTEM_MESSAGE,
        response_format=ToolStrategy(ReviewDecision),
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
    )
    structured = result.get("structured_response")
    if structured is None:
        raise RuntimeError("Missing structured_response from reviewer output")
    if isinstance(structured, ReviewDecision):
        return structured
    return ReviewDecision.model_validate(structured)


def _github_inline_comment_body(comment: ReviewInlineComment) -> str:
    """Prefix human-readable severity on GitHub so every inline visibly shows classification."""
    labels: dict[InlineCommentSeverity, str] = {
        "nitpick": "Nitpick",
        "minor_bug": "Minor bug",
        "major_bug": "Major bug",
        "blocking": "Blocking",
        "security": "Security",
        "other": "Note",
    }
    return f"**[{labels[comment.severity]}]** {comment.body}"


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
            body=_github_inline_comment_body(comment),
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
