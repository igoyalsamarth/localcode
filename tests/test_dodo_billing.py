"""Dodo billing sync and webhook idempotency."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from model.enums import BillingCycle, SubscriptionStatus
from model.tables import BillingWebhookDelivery, Organization, Subscription, User
from decimal import Decimal

from services.dodo_billing import apply_unwrapped_webhook_event, sync_subscription_from_dodo


@pytest.mark.unit
class TestDodoBillingSync:
    def test_sync_creates_subscription_and_sets_org_customer(self, db_session):
        user = User(email="buyer@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="Org", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        customer = SimpleNamespace(email="buyer@example.com", customer_id="cus_dodo_1")
        dodo = SimpleNamespace(
            metadata={"greagent_organization_id": str(org.id)},
            customer=customer,
            subscription_id="sub_dodo_1",
            status="active",
            payment_frequency_interval="Month",
            next_billing_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
            product_id="pdt_ship",
            quantity=3,
            recurring_pre_tax_amount=4999,
        )

        sync_subscription_from_dodo(db_session, dodo)
        db_session.commit()

        db_session.refresh(org)
        assert org.dodo_customer_id == "cus_dodo_1"

        row = db_session.execute(
            select(Subscription).where(Subscription.dodo_subscription_id == "sub_dodo_1")
        ).scalar_one()
        assert row.organization_id == org.id
        assert row.status == SubscriptionStatus.active
        assert row.billing_cycle == BillingCycle.monthly
        assert row.dodo_product_id == "pdt_ship"
        assert row.dodo_quantity == 3

    def test_sync_updates_existing_row(self, db_session):
        user = User(email="u@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="O", owner_user_id=user.id, dodo_customer_id="cus_x")
        db_session.add(org)
        db_session.flush()
        sub = Subscription(
            organization_id=org.id,
            dodo_subscription_id="sub_same",
            dodo_product_id="pdt_old",
            dodo_quantity=1,
            status=SubscriptionStatus.active,
            billing_cycle=BillingCycle.monthly,
        )
        db_session.add(sub)
        db_session.commit()

        customer = SimpleNamespace(email="u@example.com", customer_id="cus_x")
        dodo = SimpleNamespace(
            metadata={},
            customer=customer,
            subscription_id="sub_same",
            status="on_hold",
            payment_frequency_interval="Year",
            next_billing_date=None,
            product_id="pdt_new",
            quantity=1,
            recurring_pre_tax_amount=1000,
        )
        sync_subscription_from_dodo(db_session, dodo)
        db_session.commit()

        row = db_session.get(Subscription, sub.id)
        assert row.status == SubscriptionStatus.on_hold
        assert row.billing_cycle == BillingCycle.yearly
        assert row.dodo_product_id == "pdt_new"

    def test_apply_subscription_active_event(self, db_session):
        user = User(email="e@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="E", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        customer = SimpleNamespace(email="e@example.com", customer_id="cus_e")
        data = SimpleNamespace(
            metadata={"greagent_organization_id": str(org.id)},
            customer=customer,
            subscription_id="sub_evt",
            status="active",
            payment_frequency_interval="Month",
            next_billing_date=datetime.now(timezone.utc),
            product_id="pdt_1",
            quantity=1,
            recurring_pre_tax_amount=2500,
        )
        event = SimpleNamespace(type="subscription.active", data=data)

        apply_unwrapped_webhook_event(db_session, event)
        db_session.commit()

        assert (
            db_session.execute(
                select(Subscription).where(Subscription.dodo_subscription_id == "sub_evt")
            ).scalar_one()
            is not None
        )
        db_session.refresh(org)
        assert org.wallet_balance_usd == Decimal("0")

    def test_subscription_renewed_credits_wallet(self, db_session):
        user = User(email="r@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="R", owner_user_id=user.id)
        db_session.add(org)
        db_session.flush()

        customer = SimpleNamespace(email="r@example.com", customer_id="cus_r")
        data = SimpleNamespace(
            metadata={"greagent_organization_id": str(org.id)},
            customer=customer,
            subscription_id="sub_renew",
            status="active",
            payment_frequency_interval="Month",
            next_billing_date=datetime.now(timezone.utc),
            product_id="pdt_1",
            quantity=1,
            recurring_pre_tax_amount=1000,
        )
        event = SimpleNamespace(type="subscription.renewed", data=data)

        apply_unwrapped_webhook_event(db_session, event)
        db_session.commit()

        db_session.refresh(org)
        assert org.wallet_balance_usd == Decimal("10.00")

    def test_payment_succeeded_topup_credits_wallet(self, db_session):
        user = User(email="t@example.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(name="T", owner_user_id=user.id)
        db_session.add(org)
        db_session.commit()

        payment = SimpleNamespace(
            metadata={
                "greagent_organization_id": str(org.id),
                "greagent_wallet_topup": "true",
            },
            total_amount=500,
        )
        event = SimpleNamespace(type="payment.succeeded", data=payment)

        apply_unwrapped_webhook_event(db_session, event)
        db_session.commit()

        db_session.refresh(org)
        assert org.wallet_balance_usd == Decimal("5.00")


@pytest.mark.unit
class TestBillingWebhookDelivery:
    def test_duplicate_webhook_id_rejected_by_db(self, db_session):
        db_session.add(
            BillingWebhookDelivery(webhook_id="wh_1", event_type="subscription.active")
        )
        db_session.commit()
        dup = BillingWebhookDelivery(webhook_id="wh_1", event_type="subscription.active")
        db_session.add(dup)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
