"""Wallet usage charge formula and Dodo minor-unit conversion."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from model.tables import Organization, Repository, User
from services.wallet import (
    MIN_WALLET_USD_TO_START_AGENT,
    credit_organization_wallet_usd,
    deduct_organization_wallet_for_llm_run,
    dodo_amount_usd_from_minor_units,
    organization_spendable_balance_usd,
    usage_charge_usd_from_llm_cost,
    wallet_allows_agent_run,
)


@pytest.mark.unit
class TestUsageChargeUsd:
    def test_minimum_floor(self):
        assert usage_charge_usd_from_llm_cost(Decimal("0")) == Decimal("0.05")

    def test_rounds_up_to_cent(self):
        # (0.01 + 0.02) / 0.5 = 0.06 -> round up 0.01 = 0.06, max(0.05, 0.06) = 0.06
        assert usage_charge_usd_from_llm_cost(Decimal("0.01")) == Decimal("0.06")

    def test_example_scale(self):
        # (1.00 + 0.02) / 0.5 = 2.04
        assert usage_charge_usd_from_llm_cost(Decimal("1")) == Decimal("2.04")


@pytest.mark.unit
class TestCreditMergesPromo:
    def test_first_paid_credit_merges_remaining_promo_then_adds_amount(self, db_session):
        user = User(email="c@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        exp = datetime.now(timezone.utc) + timedelta(days=20)
        org = Organization(
            name="C",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("0"),
            promotional_balance_usd=Decimal("5"),
            promotional_balance_expires_at=exp,
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("15")
        assert org.promotional_balance_usd == Decimal("0")
        assert org.promotional_balance_expires_at is None
        assert organization_spendable_balance_usd(org) == Decimal("15")

    def test_paid_credit_merges_partially_spent_promo(self, db_session):
        user = User(email="c2@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        exp = datetime.now(timezone.utc) + timedelta(days=10)
        org = Organization(
            name="C2",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("0"),
            promotional_balance_usd=Decimal("3"),
            promotional_balance_expires_at=exp,
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("13")
        assert org.promotional_balance_usd == Decimal("0")
        assert org.promotional_balance_expires_at is None

    def test_paid_credit_after_promo_expired_does_not_revive_promo(self, db_session):
        user = User(email="c3@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        past = datetime.now(timezone.utc) - timedelta(days=1)
        org = Organization(
            name="C3",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("0"),
            promotional_balance_usd=Decimal("5"),
            promotional_balance_expires_at=past,
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("10")
        assert org.promotional_balance_usd == Decimal("0")
        assert org.promotional_balance_expires_at is None


@pytest.mark.unit
class TestDodoMinorUnits:
    def test_cents_to_usd(self):
        assert dodo_amount_usd_from_minor_units(12_34) == Decimal("12.34")


@pytest.mark.unit
class TestWalletAllowsAgentRun:
    def test_blocks_when_repository_unknown(self, db_session):
        assert wallet_allows_agent_run(db_session, "ghost", "missing") is False

    def test_blocks_below_minimum(self, db_session):
        user = User(email="w@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="W",
            owner_user_id=user.id,
            wallet_balance_usd=MIN_WALLET_USD_TO_START_AGENT - Decimal("0.01"),
        )
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=9,
            name="r",
            owner="o",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()
        assert wallet_allows_agent_run(db_session, "o", "r") is False

    def test_allows_at_minimum(self, db_session):
        user = User(email="w2@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="W2",
            owner_user_id=user.id,
            wallet_balance_usd=MIN_WALLET_USD_TO_START_AGENT,
        )
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=10,
            name="r2",
            owner="o2",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()
        assert wallet_allows_agent_run(db_session, "o2", "r2") is True

    def test_allows_when_only_promotional_balance(self, db_session):
        user = User(email="promo@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="P",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("0"),
            promotional_balance_usd=Decimal("5"),
            promotional_balance_expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db_session.add(org)
        db_session.flush()
        repo = Repository(
            organization_id=org.id,
            github_repo_id=11,
            name="rp",
            owner="op",
            default_branch="main",
        )
        db_session.add(repo)
        db_session.commit()
        assert wallet_allows_agent_run(db_session, "op", "rp") is True

    def test_deduct_draws_promotional_before_wallet(self, db_session):
        user = User(email="d@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="D",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("10"),
            promotional_balance_usd=Decimal("5"),
            promotional_balance_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        # Minimum usage charge for zero LLM cost is $0.05.
        deduct_organization_wallet_for_llm_run(db_session, oid, Decimal("0"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.promotional_balance_usd == Decimal("5") - Decimal("0.05")
        assert org.wallet_balance_usd == Decimal("10")

    def test_expired_promotional_dropped_from_spendable(self, db_session):
        user = User(email="x@e.com", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        past = datetime.now(timezone.utc) - timedelta(days=1)
        org = Organization(
            name="X",
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("3"),
            promotional_balance_usd=Decimal("5"),
            promotional_balance_expires_at=past,
        )
        db_session.add(org)
        db_session.commit()
        assert organization_spendable_balance_usd(org) == Decimal("3")
        db_session.commit()
        org = db_session.get(Organization, org.id)
        assert org.promotional_balance_usd == Decimal("0")
        assert org.promotional_balance_expires_at is None
