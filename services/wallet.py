"""
Organization wallet: USD balance for agent usage (signup credit, top-ups, subscription).

All credits live in ``wallet_balance_usd``; usage debits that field. There is no separate
promotional bucket and no lazy expiry on API reads—balance is authoritative until debited
or credited.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from sqlalchemy import select
from sqlalchemy.orm import Session

from model.tables import GitHubInstallation, Organization, Repository

CENT = Decimal("0.01")

# Minimum spendable USD before enqueueing agent tasks.
MIN_WALLET_USD_TO_START_AGENT = Decimal("2")


def organization_spendable_balance_usd(org: Organization) -> Decimal:
    """Spendable USD (currently the org wallet balance)."""
    return org.wallet_balance_usd


def usage_charge_usd_from_llm_cost(llm_cost_usd: Decimal) -> Decimal:
    """
    Wallet deduction for one agent run (USD).

    credits = (llm_cost + 0.02) / 0.5
    credits = max(0.05, round_up(credits, 0.01))
    """
    raw = (llm_cost_usd + Decimal("0.02")) / Decimal("0.5")
    rounded = raw.quantize(CENT, rounding=ROUND_CEILING)
    return max(Decimal("0.05"), rounded)


def wallet_allows_agent_run(
    session: Session,
    owner: str,
    repo_name: str,
    *,
    github_installation_id: int | None = None,
    github_repo_id: int | None = None,
) -> bool:
    """
    Require a known repo, organization, and spendable balance >= :data:`MIN_WALLET_USD_TO_START_AGENT`.

    ``Repository`` is unique per ``(organization_id, github_repo_id)``, not per ``(owner, name)``,
    so when the webhook provides ``github_installation_id`` we resolve the row via the
    installation's organization; otherwise we fall back to owner/name (and optional
    ``github_repo_id``) with a deterministic single-row limit for legacy callers.
    """
    if github_installation_id is not None and github_repo_id is not None:
        stmt = (
            select(Repository)
            .join(
                GitHubInstallation,
                GitHubInstallation.organization_id == Repository.organization_id,
            )
            .where(
                GitHubInstallation.github_installation_id == github_installation_id,
                Repository.github_repo_id == github_repo_id,
            )
        )
        repo = session.execute(stmt).scalar_one_or_none()
    else:
        stmt = select(Repository).where(
            Repository.owner == owner,
            Repository.name == repo_name,
        )
        if github_repo_id is not None:
            stmt = stmt.where(Repository.github_repo_id == github_repo_id)
        stmt = stmt.order_by(Repository.created_at.asc()).limit(1)
        repo = session.execute(stmt).scalars().first()
    if repo is None:
        return False
    org = session.get(Organization, repo.organization_id)
    if org is None:
        return False
    spendable = organization_spendable_balance_usd(org)
    return spendable >= MIN_WALLET_USD_TO_START_AGENT


def dodo_amount_usd_from_minor_units(amount_minor: int) -> Decimal:
    """Convert Dodo integer minor units (e.g. cents) to USD ``Decimal``."""
    return Decimal(int(amount_minor)) / Decimal(100)


def credit_organization_wallet_usd(
    session: Session, organization_id, amount_usd: Decimal
) -> None:
    """Add a paid Dodo credit to ``wallet_balance_usd``."""
    if amount_usd <= 0:
        return
    org = session.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if org is None:
        raise ValueError(f"Organization {organization_id} not found for wallet credit")
    org.wallet_balance_usd = org.wallet_balance_usd + amount_usd


def deduct_organization_wallet_for_llm_run(
    session: Session, organization_id, llm_cost_usd: Decimal
) -> Decimal:
    """
    Subtract usage charge from org wallet. Returns the charged amount (USD).

    Raises if the organization row is missing.
    """
    charge = usage_charge_usd_from_llm_cost(llm_cost_usd)
    org = session.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if org is None:
        raise ValueError(f"Organization {organization_id} not found for wallet debit")
    org.wallet_balance_usd = org.wallet_balance_usd - charge
    return charge
