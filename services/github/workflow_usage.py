"""
Persist LLM token usage for GitHub deep-agent runs (issue code + PR review).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from agents.usage_callback import AgentLlmUsageCallbackHandler
from db import session_scope
from logger import get_logger
from model.enums import GitHubWorkflowKind
from model.tables import AgentWorkflowUsage, Model, Repository
from services.wallet import deduct_organization_wallet_for_llm_run
from services.github.issue_payload import IssueOpenedForCoder
from services.github.pr_payload import PROpenedForReview

logger = get_logger(__name__)


def _meta_tokens(meta: Any) -> tuple[int, int]:
    if isinstance(meta, dict):
        return int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0)
    return (
        int(getattr(meta, "input_tokens", 0) or 0),
        int(getattr(meta, "output_tokens", 0) or 0),
    )


def _usage_to_json(raw: dict[str, Any]) -> dict[str, Any]:
    """JSONB-safe snapshot of per-model usage."""
    out: dict[str, Any] = {}
    for name, meta in raw.items():
        if isinstance(meta, dict):
            out[name] = dict(meta)
        else:
            inp, out_t = _meta_tokens(meta)
            out[name] = {
                "input_tokens": inp,
                "output_tokens": out_t,
                "total_tokens": inp + out_t,
            }
    return out


def _sum_tokens(raw: dict[str, Any]) -> tuple[int, int, int]:
    inp = out = 0
    for meta in raw.values():
        i, o = _meta_tokens(meta)
        inp += i
        out += o
    return inp, out, inp + out


def _compute_cost_and_catalog_model(
    session, provider: str, raw: dict[str, Any]
) -> tuple[Decimal, Model | None]:
    """Sum cost using ``Model`` rates when a catalog row matches each model name."""
    total = Decimal(0)
    first: Model | None = None
    for model_name, meta in raw.items():
        stmt = select(Model).where(Model.provider == provider, Model.name == model_name)
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            continue
        if first is None:
            first = row
        inp, out = _meta_tokens(meta)
        total += row.input_cost_per_token * inp + row.output_cost_per_token * out
    return total, first


def _resolve_repo_by_owner_name(
    session, owner: str, repo_name: str
) -> tuple[UUID | None, UUID | None]:
    stmt = select(Repository).where(
        Repository.owner == owner,
        Repository.name == repo_name,
    )
    repo = session.execute(stmt).scalar_one_or_none()
    if repo is None:
        return None, None
    return repo.id, repo.organization_id


def record_github_workflow_usage(
    *,
    workflow: GitHubWorkflowKind,
    owner: str,
    repo_name: str,
    github_full_name: str,
    github_item_number: int,
    thread_id: str,
    usage_cb: AgentLlmUsageCallbackHandler,
    provider: str,
) -> None:
    """
    Insert one ``AgentWorkflowUsage`` row after an agent run.

    Does not raise — logs on failure so billing never breaks the workflow.
    """
    raw = dict(usage_cb.usage_metadata)
    serializable = _usage_to_json(raw) if raw else None
    inp, out, total = _sum_tokens(raw)
    model_label = ", ".join(sorted(raw.keys())) if raw else "unknown"

    try:
        with session_scope() as session:
            repo_id, org_id = _resolve_repo_by_owner_name(session, owner, repo_name)
            cost, catalog_model = _compute_cost_and_catalog_model(session, provider, raw)

            credits_charged = Decimal("0")
            if org_id is not None:
                credits_charged = deduct_organization_wallet_for_llm_run(
                    session, org_id, cost
                )

            row = AgentWorkflowUsage(
                workflow=workflow,
                organization_id=org_id,
                repository_id=repo_id,
                github_full_name=github_full_name,
                github_item_number=github_item_number,
                langgraph_thread_id=thread_id,
                provider=provider,
                model_name=model_label,
                model_id=catalog_model.id if catalog_model else None,
                input_tokens=inp,
                output_tokens=out,
                total_tokens=total,
                usage_by_model=serializable,
                cost=cost,
                credits_charged_usd=credits_charged,
            )
            session.add(row)
        logger.info(
            "Recorded %s workflow usage: %s#%s model=%s in=%s out=%s total=%s",
            workflow.value,
            github_full_name,
            github_item_number,
            model_label,
            inp,
            out,
            total,
        )
    except Exception:
        logger.exception(
            "Failed to record %s workflow usage for %s#%s",
            workflow.value,
            github_full_name,
            github_item_number,
        )


def record_issue_workflow_usage(
    issue: IssueOpenedForCoder,
    thread_id: str,
    usage_cb: AgentLlmUsageCallbackHandler,
    *,
    provider: str,
) -> None:
    record_github_workflow_usage(
        workflow=GitHubWorkflowKind.code,
        owner=issue.owner,
        repo_name=issue.repo_name,
        github_full_name=issue.full_name,
        github_item_number=issue.issue_number,
        thread_id=thread_id,
        usage_cb=usage_cb,
        provider=provider,
    )


def record_pr_workflow_usage(
    pr: PROpenedForReview,
    thread_id: str,
    usage_cb: AgentLlmUsageCallbackHandler,
    *,
    provider: str,
) -> None:
    record_github_workflow_usage(
        workflow=GitHubWorkflowKind.review,
        owner=pr.owner,
        repo_name=pr.repo_name,
        github_full_name=pr.full_name,
        github_item_number=pr.pr_number,
        thread_id=thread_id,
        usage_cb=usage_cb,
        provider=provider,
    )
