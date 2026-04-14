"""Wallet usage charge formula and Dodo minor-unit conversion."""

from decimal import Decimal

import pytest

from model.tables import GitHubInstallation, Organization, Repository, User
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
class TestCreditWallet:
    def test_paid_credit_adds_to_wallet(self, db_session):
        user = User(email="c@e.com", username="c", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="C",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("5"),
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("15")
        assert organization_spendable_balance_usd(org) == Decimal("15")

    def test_paid_credit_stacks_on_existing_balance(self, db_session):
        user = User(email="c2@e.com", username="c2", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="C2",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("3"),
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("13")

    def test_paid_credit_from_zero(self, db_session):
        user = User(email="c3@e.com", username="c3", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="C3",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("0"),
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        credit_organization_wallet_usd(db_session, oid, Decimal("10"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("10")


@pytest.mark.unit
class TestDodoMinorUnits:
    def test_cents_to_usd(self):
        assert dodo_amount_usd_from_minor_units(12_34) == Decimal("12.34")


@pytest.mark.unit
class TestWalletAllowsAgentRun:
    def test_blocks_when_repository_unknown(self, db_session):
        assert wallet_allows_agent_run(db_session, "ghost", "missing") is False

    def test_blocks_below_minimum(self, db_session):
        user = User(email="w@e.com", username="w", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="W",
            is_personal=False,
            created_by_user_id=user.id,
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
        user = User(email="w2@e.com", username="w2", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="W2",
            is_personal=False,
            created_by_user_id=user.id,
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

    def test_allows_when_wallet_has_signup_or_topup_credit(self, db_session):
        user = User(email="promo@e.com", username="promo", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="P",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("5"),
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

    def test_duplicate_owner_name_resolved_by_installation(self, db_session):
        """Same GitHub slug can exist on multiple org rows; installation picks the billed org."""
        gh_repo_id = 88_888
        for i, (email, username, inst_id, balance) in enumerate(
            [
                ("dupa@e.com", "dupa", 501, Decimal("5")),
                ("dupb@e.com", "dupb", 502, Decimal("0")),
            ]
        ):
            user = User(email=email, username=username, auth_provider="github")
            db_session.add(user)
            db_session.flush()
            org = Organization(
                name=f"O{i}",
                is_personal=False,
                created_by_user_id=user.id,
                owner_user_id=user.id,
                wallet_balance_usd=balance,
            )
            db_session.add(org)
            db_session.flush()
            db_session.add(
                GitHubInstallation(
                    organization_id=org.id,
                    github_installation_id=inst_id,
                    account_name="acct",
                )
            )
            db_session.add(
                Repository(
                    organization_id=org.id,
                    github_repo_id=gh_repo_id,
                    name="r",
                    owner="o",
                    default_branch="main",
                )
            )
        db_session.commit()

        assert wallet_allows_agent_run(
            db_session,
            "o",
            "r",
            github_installation_id=501,
            github_repo_id=gh_repo_id,
        )
        assert not wallet_allows_agent_run(
            db_session,
            "o",
            "r",
            github_installation_id=502,
            github_repo_id=gh_repo_id,
        )

    def test_deduct_from_wallet(self, db_session):
        user = User(email="d@e.com", username="d", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="D",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("15"),
        )
        db_session.add(org)
        db_session.commit()
        oid = org.id
        # Minimum usage charge for zero LLM cost is $0.05.
        deduct_organization_wallet_for_llm_run(db_session, oid, Decimal("0"))
        db_session.commit()
        org = db_session.get(Organization, oid)
        assert org.wallet_balance_usd == Decimal("15") - Decimal("0.05")

    def test_spendable_matches_wallet(self, db_session):
        user = User(email="x@e.com", username="x", auth_provider="github")
        db_session.add(user)
        db_session.flush()
        org = Organization(
            name="X",
            is_personal=False,
            created_by_user_id=user.id,
            owner_user_id=user.id,
            wallet_balance_usd=Decimal("8"),
        )
        db_session.add(org)
        db_session.commit()
        assert organization_spendable_balance_usd(org) == Decimal("8")
