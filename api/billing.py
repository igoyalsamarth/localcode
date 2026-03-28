"""Dodo Payments: checkout, customer portal, webhooks."""

from __future__ import annotations

import asyncio
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.deps import get_current_org_id, get_current_user_id
from constants import (
    CLIENT_URL,
    DODO_PAYMENTS_API_KEY,
    DODO_PAYMENTS_ENVIRONMENT,
    DODO_PAYMENTS_WEBHOOK_KEY,
    DODO_PRODUCT_ID_SHIP_GOBLIN,
)
from db import session_scope
from logger import get_logger
from model.tables import BillingWebhookDelivery, Organization, Subscription, User
from services.dodo_billing import apply_unwrapped_webhook_event

logger = get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

PlanId = Literal["ship_goblin"]


def _dodo_environment() -> Literal["test_mode", "live_mode"]:
    v = DODO_PAYMENTS_ENVIRONMENT.strip()
    if v not in ("test_mode", "live_mode"):
        raise ValueError(
            "DODO_PAYMENTS_ENVIRONMENT must be 'test_mode' or 'live_mode', "
            f"got {v!r}"
        )
    return cast(Literal["test_mode", "live_mode"], v)


def _product_id_for_plan(plan: PlanId) -> str | None:
    if plan == "ship_goblin":
        return DODO_PRODUCT_ID_SHIP_GOBLIN or None
    return None


def _dodo_client():
    from dodopayments import DodoPayments

    if not DODO_PAYMENTS_API_KEY:
        return None
    return DodoPayments(
        bearer_token=DODO_PAYMENTS_API_KEY,
        environment=_dodo_environment(),
        webhook_key=DODO_PAYMENTS_WEBHOOK_KEY or None,
    )


def _dodo_client_for_request():
    """Like :func:`_dodo_client` but invalid configuration becomes HTTP 500."""
    try:
        return _dodo_client()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class CheckoutSessionRequest(BaseModel):
    plan: PlanId = Field(description="Paid plan to start checkout for")


class BillingCheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class CustomerPortalSessionResponse(BaseModel):
    portal_url: str


class BillingSubscriptionOut(BaseModel):
    dodo_subscription_id: str
    dodo_product_id: str
    status: str
    billing_cycle: str
    quantity: int
    current_period_end: str | None


class BillingSubscriptionResponse(BaseModel):
    dodo_customer_id: str | None
    subscription: BillingSubscriptionOut | None


@router.post("/checkout-session", response_model=BillingCheckoutSessionResponse)
async def create_checkout_session(
    body: CheckoutSessionRequest,
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    """
    Create a Dodo hosted checkout session for the given plan.
    Caller must be authenticated; customer email is taken from the user record.
    """
    product_id = _product_id_for_plan(body.plan)
    if not product_id:
        raise HTTPException(
            status_code=503,
            detail="Paid plan is not configured (set DODO_PRODUCT_ID_SHIP_GOBLIN on the server).",
        )

    client = _dodo_client_for_request()
    if not client:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured (set DODO_PAYMENTS_API_KEY on the server).",
        )

    with session_scope() as db:
        stmt = select(User).where(User.id == user_id)
        user = db.execute(stmt).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        email = user.email
        display_name = user.name or user.username or user.github_login or email.split("@")[0]

    base = CLIENT_URL.rstrip("/")
    return_url = f"{base}/pricing/success"
    cancel_url = f"{base}/pricing"

    metadata = {
        "greagent_user_id": str(user_id),
        "greagent_organization_id": str(org_id),
    }

    def _create():
        return client.checkout_sessions.create(
            product_cart=[{"product_id": product_id, "quantity": 1}],
            customer={"email": email, "name": display_name},
            return_url=return_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )

    try:
        session = await asyncio.to_thread(_create)
    except Exception as e:
        logger.exception("Dodo checkout_sessions.create failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Could not start checkout. Try again or contact support.",
        ) from e

    url = session.checkout_url
    if not url:
        raise HTTPException(
            status_code=502,
            detail="Checkout session created without a URL.",
        )

    return BillingCheckoutSessionResponse(checkout_url=url, session_id=session.session_id)


@router.get("/subscription", response_model=BillingSubscriptionResponse)
async def get_billing_subscription(org_id: UUID = Depends(get_current_org_id)):
    """Return Dodo linkage and the latest subscription row for the session organization."""
    with session_scope() as db:
        org = db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        stmt = (
            select(Subscription)
            .where(Subscription.organization_id == org_id)
            .order_by(Subscription.updated_at.desc())
        )
        sub = db.execute(stmt).scalars().first()

        if sub is None:
            return BillingSubscriptionResponse(
                dodo_customer_id=org.dodo_customer_id,
                subscription=None,
            )

        cpe = sub.current_period_end
        cpe_s = cpe.isoformat() if cpe else None

        return BillingSubscriptionResponse(
            dodo_customer_id=org.dodo_customer_id,
            subscription=BillingSubscriptionOut(
                dodo_subscription_id=sub.dodo_subscription_id,
                dodo_product_id=sub.dodo_product_id,
                status=sub.status.value,
                billing_cycle=sub.billing_cycle.value,
                quantity=sub.dodo_quantity,
                current_period_end=cpe_s,
            ),
        )


@router.post("/customer-portal-session", response_model=CustomerPortalSessionResponse)
async def create_customer_portal_session(org_id: UUID = Depends(get_current_org_id)):
    """Create a short-lived Dodo customer portal URL for the org’s paying customer."""
    with session_scope() as db:
        org = db.get(Organization, org_id)
        if org is None or not org.dodo_customer_id:
            raise HTTPException(
                status_code=400,
                detail="No Dodo customer on this organization yet. Subscribe first.",
            )
        customer_id = org.dodo_customer_id

    client = _dodo_client_for_request()
    if not client:
        raise HTTPException(status_code=503, detail="Billing is not configured")

    return_url = f"{CLIENT_URL.rstrip('/')}/settings"

    def _portal():
        return client.customers.customer_portal.create(
            customer_id,
            return_url=return_url,
        )

    try:
        portal = await asyncio.to_thread(_portal)
    except Exception as e:
        logger.exception("Dodo customer_portal.create failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Could not open billing portal.",
        ) from e

    return CustomerPortalSessionResponse(portal_url=portal.link)


@router.post("/webhook")
async def dodo_webhook(request: Request):
    """
    Dodo Payments webhook endpoint. Verifies Standard Webhooks signatures.
    Configure in the Dodo dashboard, e.g. ``POST https://<api-host>/billing/webhook``.
    """
    if not DODO_PAYMENTS_API_KEY or not DODO_PAYMENTS_WEBHOOK_KEY:
        raise HTTPException(status_code=503, detail="Webhook verification is not configured")

    client = _dodo_client_for_request()
    if not client:
        raise HTTPException(status_code=503, detail="Billing client not available")

    raw = await request.body()
    payload = raw.decode("utf-8")
    hdrs = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }

    try:
        event = client.webhooks.unwrap(payload, headers=hdrs)
    except Exception as e:
        logger.warning("Dodo webhook signature or payload invalid: %s", e)
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from e

    etype = str(getattr(event, "type", type(event).__name__))
    webhook_id = request.headers.get("webhook-id", "") or ""

    logger.info("Dodo webhook received: %s id=%s", etype, webhook_id or "(none)")

    try:
        with session_scope() as db:
            if webhook_id.strip():
                if db.get(BillingWebhookDelivery, webhook_id) is not None:
                    logger.info("Duplicate Dodo webhook ignored: %s", webhook_id)
                    return {"received": True, "duplicate": True}
                db.add(
                    BillingWebhookDelivery(webhook_id=webhook_id, event_type=etype)
                )
            apply_unwrapped_webhook_event(db, event)
    except IntegrityError:
        logger.info("Duplicate Dodo webhook (race on id): %s", webhook_id)
        return {"received": True, "duplicate": True}
    except ValueError as e:
        logger.exception("Dodo webhook could not be applied: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {"received": True}
