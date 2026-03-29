"""Apply Dodo Payments webhook payloads to ORM state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from logger import get_logger
from model.enums import BillingCycle, SubscriptionStatus
from model.tables import Organization, Subscription
from services.wallet import (
    credit_organization_wallet_usd,
    dodo_amount_usd_from_minor_units,
)

if TYPE_CHECKING:
    from dodopayments.types.subscription import Subscription as DodoSubscriptionPayload

logger = get_logger(__name__)

_SUBSCRIPTION_WEBHOOK_TYPES = frozenset(
    {
        "subscription.active",
        "subscription.on_hold",
        "subscription.renewed",
        "subscription.updated",
        "subscription.plan_changed",
        "subscription.cancelled",
        "subscription.failed",
        "subscription.expired",
    }
)

_INTERVAL_TO_CYCLE: dict[str, BillingCycle] = {
    "Day": BillingCycle.daily,
    "Week": BillingCycle.weekly,
    "Month": BillingCycle.monthly,
    "Year": BillingCycle.yearly,
}


def map_dodo_subscription_status(raw: str) -> SubscriptionStatus:
    try:
        return SubscriptionStatus(raw)
    except ValueError as e:
        raise ValueError(f"Unknown Dodo subscription status: {raw!r}") from e


def map_dodo_interval(interval: str) -> BillingCycle:
    try:
        return _INTERVAL_TO_CYCLE[interval]
    except KeyError as e:
        raise ValueError(
            f"Unknown Dodo payment_frequency_interval: {interval!r} "
            f"(expected one of {list(_INTERVAL_TO_CYCLE)})"
        ) from e


def resolve_organization_id(
    session: Session,
    metadata: dict[str, str],
    dodo_customer_id: str,
) -> UUID:
    org = session.execute(
        select(Organization).where(Organization.dodo_customer_id == dodo_customer_id)
    ).scalar_one_or_none()
    if org is not None:
        return org.id

    org_s = metadata.get("greagent_organization_id")
    if org_s:
        try:
            oid = UUID(org_s)
        except ValueError as e:
            raise ValueError(
                f"Invalid greagent_organization_id in metadata: {org_s!r}"
            ) from e
        org = session.get(Organization, oid)
        if org is None:
            raise ValueError(
                f"No organization {oid} for greagent_organization_id metadata"
            )
        return org.id

    raise ValueError(
        "Cannot resolve organization: set greagent_organization_id on checkout metadata "
        "or match an existing Organization.dodo_customer_id"
    )


def sync_subscription_from_dodo(session: Session, dodo_sub: DodoSubscriptionPayload) -> None:
    """Upsert :class:`~model.tables.Subscription` from a Dodo subscription payload."""
    meta = dict(dodo_sub.metadata or {})
    dodo_customer_id = dodo_sub.customer.customer_id

    org_id = resolve_organization_id(session, meta, dodo_customer_id)
    org = session.get(Organization, org_id)
    if org is None:
        raise ValueError(f"Organization {org_id} not found after resolution")
    org.dodo_customer_id = dodo_customer_id

    sub_id = dodo_sub.subscription_id
    stmt = select(Subscription).where(Subscription.dodo_subscription_id == sub_id)
    row = session.execute(stmt).scalar_one_or_none()

    status = map_dodo_subscription_status(str(dodo_sub.status))
    cycle = map_dodo_interval(str(dodo_sub.payment_frequency_interval))
    next_end: datetime | None = dodo_sub.next_billing_date
    if next_end is not None and next_end.tzinfo is None:
        next_end = next_end.replace(tzinfo=timezone.utc)

    if row is None:
        row = Subscription(
            organization_id=org_id,
            dodo_subscription_id=sub_id,
            dodo_product_id=dodo_sub.product_id,
            dodo_quantity=int(dodo_sub.quantity),
            status=status,
            billing_cycle=cycle,
            current_period_end=next_end,
        )
        session.add(row)
        logger.info("Created subscription row for Dodo %s org=%s", sub_id, org_id)
        return

    row.organization_id = org_id
    row.dodo_product_id = dodo_sub.product_id
    row.dodo_quantity = int(dodo_sub.quantity)
    row.status = status
    row.billing_cycle = cycle
    row.current_period_end = next_end
    logger.info("Updated subscription row for Dodo %s org=%s", sub_id, org_id)


def credit_wallet_for_subscription_renewal(session: Session, dodo_sub: object) -> None:
    """
    Add one billing period’s subscription amount to the org wallet (USD).

    Intended for ``subscription.renewed`` (includes the first billing period per Dodo).
    """
    meta = dict(getattr(dodo_sub, "metadata", None) or {})
    dodo_customer_id = dodo_sub.customer.customer_id
    org_id = resolve_organization_id(session, meta, dodo_customer_id)
    minor = getattr(dodo_sub, "recurring_pre_tax_amount", None)
    if minor is None:
        return
    usd = dodo_amount_usd_from_minor_units(int(minor))
    credit_organization_wallet_usd(session, org_id, usd)
    logger.info(
        "Wallet credited for subscription renewal org=%s amount_usd=%s",
        org_id,
        usd,
    )


def credit_wallet_for_topup_payment(session: Session, payment: object) -> None:
    """Credit wallet when a one-off checkout was started as a wallet top-up."""
    meta = dict(getattr(payment, "metadata", None) or {})
    flag = str(meta.get("greagent_wallet_topup", "")).lower()
    if flag not in ("1", "true", "yes"):
        return
    org_s = meta.get("greagent_organization_id")
    if not org_s:
        raise ValueError(
            "wallet top-up payment missing greagent_organization_id in metadata"
        )
    try:
        oid = UUID(org_s)
    except ValueError as e:
        raise ValueError(
            f"Invalid greagent_organization_id in top-up metadata: {org_s!r}"
        ) from e
    org = session.get(Organization, oid)
    if org is None:
        raise ValueError(f"No organization {oid} for wallet top-up metadata")
    minor = int(getattr(payment, "total_amount"))
    usd = dodo_amount_usd_from_minor_units(minor)
    credit_organization_wallet_usd(session, oid, usd)
    logger.info("Wallet credited for top-up org=%s amount_usd=%s", oid, usd)


def apply_unwrapped_webhook_event(session: Session, event: object) -> None:
    """Dispatch a verified Dodo webhook model to table updates."""
    etype = getattr(event, "type", None)

    if etype in _SUBSCRIPTION_WEBHOOK_TYPES:
        data = getattr(event, "data", None)
        if data is None:
            raise ValueError(f"Dodo webhook {etype!r} missing data payload")
        sync_subscription_from_dodo(session, data)
        if etype == "subscription.renewed":
            credit_wallet_for_subscription_renewal(session, data)
        return

    if etype == "payment.succeeded":
        data = getattr(event, "data", None)
        if data is None:
            raise ValueError("Dodo webhook payment.succeeded missing data payload")
        credit_wallet_for_topup_payment(session, data)
        return

    logger.debug("Dodo webhook type not persisted: %s", etype)
