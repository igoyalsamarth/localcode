"""
Organization wallet: paid balance, time-limited signup promo, usage charges.

- ``wallet_balance_usd``: subscription renewals, top-ups, and paid-in funds (no expiry).
- ``promotional_balance_usd`` + ``promotional_balance_expires_at``: signup promo only.
  Usage debits promo first, then paid wallet.

If the org **never** receives paid credit while promo is active, promo expires after
``SIGNUP_PROMO_DURATION_DAYS`` (lazy drop via :func:`zero_expired_promotional_balance`).

The first **positive** paid credit (top-up or subscription) while promo is still unexpired
moves **all remaining** promo into ``wallet_balance_usd`` and clears promo (no further expiry).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

from sqlalchemy import select
from sqlalchemy.orm import Session

from constants import SIGNUP_PROMO_DURATION_DAYS, SIGNUP_PROMO_WALLET_USD
from model.tables import Organization, Repository

CENT = Decimal("0.01")

# Minimum spendable (paid + unexpired promo) USD before enqueueing agent tasks.
MIN_WALLET_USD_TO_START_AGENT = Decimal("2")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now_utc(now: datetime | None = None) -> datetime:
    return _as_utc(now or datetime.now(timezone.utc))


def signup_promotional_credit_defaults(
    now: datetime | None = None,
) -> tuple[Decimal, datetime]:
    """``(promotional_balance_usd, expires_at)`` for a newly created organization."""
    n = _now_utc(now)
    end = n + timedelta(days=SIGNUP_PROMO_DURATION_DAYS)
    return SIGNUP_PROMO_WALLET_USD, end


def zero_expired_promotional_balance(
    org: Organization, now: datetime | None = None
) -> None:
    """
    Drop promotional balance when it is expired or inconsistent (mutates ``org``).

    Promo must always carry an expiry while ``promotional_balance_usd`` > 0.
    """
    if org.promotional_balance_usd <= 0:
        org.promotional_balance_expires_at = None
        return
    if org.promotional_balance_expires_at is None:
        org.promotional_balance_usd = Decimal("0")
        return
    n = _now_utc(now)
    exp = _as_utc(org.promotional_balance_expires_at)
    if n >= exp:
        org.promotional_balance_usd = Decimal("0")
        org.promotional_balance_expires_at = None


def organization_spendable_balance_usd(org: Organization, now: datetime | None = None) -> Decimal:
    """Paid wallet plus active (unexpired) promotional balance."""
    zero_expired_promotional_balance(org, now)
    return org.wallet_balance_usd + org.promotional_balance_usd


def _merge_unexpired_signup_promo_into_paid_wallet(
    org: Organization, now: datetime | None = None
) -> None:
    """
    Move remaining signup promo into paid wallet if it is still unexpired.

    Caller must hold a row lock on ``org``. Used when applying paid Dodo credits.
    After :func:`zero_expired_promotional_balance`, any positive promo is necessarily active.
    """
    zero_expired_promotional_balance(org, now)
    if org.promotional_balance_usd <= 0:
        return
    org.wallet_balance_usd = org.wallet_balance_usd + org.promotional_balance_usd
    org.promotional_balance_usd = Decimal("0")
    org.promotional_balance_expires_at = None


def usage_charge_usd_from_llm_cost(llm_cost_usd: Decimal) -> Decimal:
    """
    Wallet deduction for one agent run (USD).

    credits = (llm_cost + 0.02) / 0.5
    credits = max(0.05, round_up(credits, 0.01))
    """
    raw = (llm_cost_usd + Decimal("0.02")) / Decimal("0.5")
    rounded = raw.quantize(CENT, rounding=ROUND_CEILING)
    return max(Decimal("0.05"), rounded)


def wallet_allows_agent_run(session: Session, owner: str, repo_name: str) -> bool:
    """Require a known repo, organization, and spendable balance >= :data:`MIN_WALLET_USD_TO_START_AGENT`."""
    stmt = select(Repository).where(
        Repository.owner == owner,
        Repository.name == repo_name,
    )
    repo = session.execute(stmt).scalar_one_or_none()
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
    """
    Add a paid Dodo credit to ``wallet_balance_usd``.

    If signup promo is still active, remaining promo is folded into paid wallet first,
    then ``amount_usd`` is added (so it becomes permanent balance with no promo expiry).
    """
    if amount_usd <= 0:
        return
    org = session.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if org is None:
        raise ValueError(f"Organization {organization_id} not found for wallet credit")
    _merge_unexpired_signup_promo_into_paid_wallet(org)
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
    zero_expired_promotional_balance(org)
    from_promo = min(charge, org.promotional_balance_usd)
    org.promotional_balance_usd = org.promotional_balance_usd - from_promo
    from_wallet = charge - from_promo
    org.wallet_balance_usd = org.wallet_balance_usd - from_wallet
    return charge
