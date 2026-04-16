"""
Persist LLM token usage for GitHub deep-agent runs (issue code + PR review).

Token counts and catalog rates yield an internal ``llm_cost_usd``. The persisted ``cost``
and wallet debits both use :func:`services.wallet.usage_charge_usd_from_llm_cost` on that
value so usage totals match what was charged.
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
from model.tables import (
    AgentWorkflowUsage,
    GitHubInstallation,
    Model,
    Organization,
    Repository,
    User,
)
from services.wallet import (
    deduct_organization_wallet_for_llm_run,
    usage_charge_usd_from_llm_cost,
)
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


def _compute_llm_cost_usd_and_catalog_model(
    session, provider: str, raw: dict[str, Any]
) -> tuple[Decimal, Model | None]:
    """Token-derived LLM spend (USD) from catalog ``Model`` rates (input before wallet formula)."""
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


def _resolve_repository(
    session,
    owner: str,
    repo_name: str,
    *,
    github_repo_id: int | None = None,
    github_installation_id: int | None = None,
) -> tuple[UUID | None, UUID | None]:
    """
    Map a GitHub repo to our ``Repository`` row.

    ``owner``/``name`` are not unique across organizations, so callers should pass
    ``github_repo_id`` (and ideally ``github_installation_id``) from the webhook when
    available.
    """
    # Definitive: installation belongs to exactly one org; (org, github_repo_id) is unique.
    if github_installation_id is not None and github_repo_id is not None:
        stmt = (
            select(Repository)
            .join(Organization, Repository.organization_id == Organization.id)
            .join(
                GitHubInstallation,
                GitHubInstallation.organization_id == Organization.id,
            )
            .where(
                GitHubInstallation.github_installation_id == github_installation_id,
                Repository.github_repo_id == github_repo_id,
            )
        )
        repo = session.scalars(stmt).first()
        if repo is not None:
            return repo.id, repo.organization_id

    # Same GitHub repo can exist under multiple org rows; pick one deterministically.
    if github_repo_id is not None:
        stmt = (
            select(Repository)
            .where(
                Repository.github_repo_id == github_repo_id,
                Repository.owner == owner,
                Repository.name == repo_name,
            )
            .order_by(Repository.created_at.asc())
            .limit(1)
        )
        repo = session.scalars(stmt).first()
        if repo is not None:
            return repo.id, repo.organization_id

    stmt = (
        select(Repository)
        .where(
            Repository.owner == owner,
            Repository.name == repo_name,
        )
        .order_by(Repository.created_at.asc())
        .limit(1)
    )
    repo = session.scalars(stmt).first()
    if repo is None:
        return None, None
    return repo.id, repo.organization_id


def _resolve_trigger_user_id(
    session,
    owner: str,
    repo_name: str,
    sender_login: str | None,
    *,
    github_repo_id: int | None = None,
    github_installation_id: int | None = None,
) -> UUID | None:
    if not sender_login or not sender_login.strip():
        return None
    repo_id, org_id = _resolve_repository(
        session,
        owner,
        repo_name,
        github_repo_id=github_repo_id,
        github_installation_id=github_installation_id,
    )
    if org_id is None:
        return None
    user = session.execute(
        select(User).where(User.github_login == sender_login.strip())
    ).scalar_one_or_none()
    if user is None:
        return None
    org = session.get(Organization, org_id)
    if org is None or org.owner_user_id != user.id:
        return None
    return user.id


def record_github_workflow_usage(
    *,
    workflow: GitHubWorkflowKind,
    owner: str,
    repo_name: str,
    github_full_name: str,
    github_item_number: int,
    run_id: str,
    usage_cb: AgentLlmUsageCallbackHandler,
    provider: str,
    github_sender_login: str | None = None,
    github_repo_id: int | None = None,
    github_installation_id: int | None = None,
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
            repo_id, org_id = _resolve_repository(
                session,
                owner,
                repo_name,
                github_repo_id=github_repo_id,
                github_installation_id=github_installation_id,
            )
            trigger_uid = _resolve_trigger_user_id(
                session,
                owner,
                repo_name,
                github_sender_login,
                github_repo_id=github_repo_id,
                github_installation_id=github_installation_id,
            )
            llm_cost_usd, catalog_model = _compute_llm_cost_usd_and_catalog_model(
                session, provider, raw
            )
            # Same USD amount the wallet uses (and :func:`deduct_organization_wallet_for_llm_run`).
            wallet_charge_usd = usage_charge_usd_from_llm_cost(llm_cost_usd)

            credits_charged = Decimal("0")
            if org_id is not None:
                credits_charged = deduct_organization_wallet_for_llm_run(
                    session, org_id, llm_cost_usd
                )

            row = AgentWorkflowUsage(
                workflow=workflow,
                organization_id=org_id,
                trigger_user_id=trigger_uid,
                repository_id=repo_id,
                github_full_name=github_full_name,
                github_item_number=github_item_number,
                run_id=run_id,
                provider=provider,
                model_name=model_label,
                model_id=catalog_model.id if catalog_model else None,
                input_tokens=inp,
                output_tokens=out,
                total_tokens=total,
                usage_by_model=serializable,
                cost=wallet_charge_usd,
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
    run_id: str,
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
        run_id=run_id,
        usage_cb=usage_cb,
        provider=provider,
        github_sender_login=issue.github_sender_login,
        github_repo_id=issue.github_repo_id,
        github_installation_id=issue.github_installation_id,
    )


def record_pr_workflow_usage(
    pr: PROpenedForReview,
    run_id: str,
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
        run_id=run_id,
        usage_cb=usage_cb,
        provider=provider,
        github_sender_login=pr.github_sender_login,
        github_repo_id=pr.github_repo_id,
        github_installation_id=pr.github_installation_id,
    )
