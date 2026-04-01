"""
Pydantic schemas mirroring ORM models. Use model_config(from_attributes=True)
for ORM -> schema conversion. Shared enums in model.enums.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from model.enums import AgentType, BillingCycle, MemberRole, SubscriptionStatus


def _orm_config() -> ConfigDict:
    return ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Users & Organizations
# ---------------------------------------------------------------------------


class UserBase(BaseModel):
    email: str
    username: str
    name: str | None = None
    github_user_id: int | None = None
    github_login: str | None = None
    avatar_url: str | None = None
    auth_provider: str
    onboarded: bool = False


class UserCreate(UserBase):
    pass


class User(UserBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class OrganizationBase(BaseModel):
    name: str
    is_personal: bool = False
    created_by_user_id: UUID
    owner_user_id: UUID
    github_installation_id: int | None = None


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class OrganizationMemberBase(BaseModel):
    organization_id: UUID
    user_id: UUID
    role: MemberRole


class OrganizationMemberCreate(OrganizationMemberBase):
    pass


class OrganizationMember(OrganizationMemberBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubInstallationBase(BaseModel):
    organization_id: UUID
    github_installation_id: int
    account_name: str
    access_token_encrypted: str | None = None


class GitHubInstallationCreate(GitHubInstallationBase):
    pass


class GitHubInstallation(GitHubInstallationBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class RepositoryBase(BaseModel):
    organization_id: UUID
    github_repo_id: int
    name: str
    owner: str
    private: bool = False
    default_branch: str
    active: bool = True


class RepositoryCreate(RepositoryBase):
    pass


class Repository(RepositoryBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Agents & Models
# ---------------------------------------------------------------------------


class ModelBase(BaseModel):
    provider: str
    name: str
    input_cost_per_token: Decimal = Decimal("0")
    output_cost_per_token: Decimal = Decimal("0")


class ModelCreate(ModelBase):
    pass


class Model(ModelBase):
    model_config = _orm_config()

    id: UUID


class AgentBase(BaseModel):
    organization_id: UUID
    name: str
    type: AgentType


class AgentCreate(AgentBase):
    pass


class Agent(AgentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


class RepositoryAgentBase(BaseModel):
    repository_id: UUID
    agent_id: UUID
    model_id: UUID
    enabled: bool = True
    config_json: dict | None = None


class RepositoryAgentCreate(RepositoryAgentBase):
    pass


class RepositoryAgent(RepositoryAgentBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


class SubscriptionBase(BaseModel):
    organization_id: UUID
    dodo_subscription_id: str
    dodo_product_id: str
    dodo_quantity: int = 1
    status: SubscriptionStatus
    billing_cycle: BillingCycle
    current_period_end: datetime | None = None


class SubscriptionCreate(SubscriptionBase):
    pass


class Subscription(SubscriptionBase):
    model_config = _orm_config()

    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
