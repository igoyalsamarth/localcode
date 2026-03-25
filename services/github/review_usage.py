"""
Persist LLM token usage for the GitHub review workflow (pricing / planning).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from agents.usage_callback import CoderLlmUsageCallbackHandler
from db import session_scope
from logger import get_logger
from model.tables import CoderWorkflowUsage, Model, Repository
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


def _resolve_repo(
    session, pr: PROpenedForReview
) -> tuple[UUID | None, UUID | None]:
    stmt = select(Repository).where(
        Repository.owner == pr.owner,
        Repository.name == pr.repo_name,
    )
    repo = session.execute(stmt).scalar_one_or_none()
    if repo is None:
        return None, None
    return repo.id, repo.organization_id


def record_review_workflow_usage(
    pr: PROpenedForReview,
    thread_id: str,
    usage_cb: CoderLlmUsageCallbackHandler,
    *,
    provider: str,
    fallback_model_name: str,
) -> None:
    """
    Insert one ``CoderWorkflowUsage`` row after a review agent run.

    Reuses the same table as coder workflow for simplicity; differentiates by thread_id pattern.
    Does not raise — logs on failure so billing never breaks the reviewer.
    """
    raw = dict(usage_cb.usage_metadata)
    serializable = _usage_to_json(raw) if raw else None
    inp, out, total = _sum_tokens(raw)
    model_label = (
        ", ".join(sorted(raw.keys())) if raw else fallback_model_name
    )

    try:
        with session_scope() as session:
            repo_id, org_id = _resolve_repo(session, pr)
            cost, catalog_model = _compute_cost_and_catalog_model(session, provider, raw)
            if catalog_model is None and raw:
                stmt = select(Model).where(
                    Model.provider == provider,
                    Model.name == fallback_model_name,
                )
                catalog_model = session.execute(stmt).scalar_one_or_none()
                if catalog_model and inp + out > 0:
                    cost = (
                        catalog_model.input_cost_per_token * inp
                        + catalog_model.output_cost_per_token * out
                    )

            row = CoderWorkflowUsage(
                organization_id=org_id,
                repository_id=repo_id,
                github_full_name=pr.full_name,
                issue_number=pr.pr_number,
                langgraph_thread_id=thread_id,
                provider=provider,
                model_name=model_label,
                model_id=catalog_model.id if catalog_model else None,
                input_tokens=inp,
                output_tokens=out,
                total_tokens=total,
                usage_by_model=serializable,
                cost=cost,
            )
            session.add(row)
        logger.info(
            "Recorded review workflow usage: %s#%s model=%s in=%s out=%s total=%s",
            pr.full_name,
            pr.pr_number,
            model_label,
            inp,
            out,
            total,
        )
    except Exception:
        logger.exception(
            "Failed to record review workflow usage for %s#%s",
            pr.full_name,
            pr.pr_number,
        )
