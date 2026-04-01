"""Current organization (single user): profile and rename."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_current_org_id, get_current_user_id
from api.user_org import require_org_membership
from db import session_scope

router = APIRouter(prefix="/organization", tags=["organization"])


class OrganizationOut(BaseModel):
    id: str
    name: str
    is_personal: bool


class OrganizationPatchBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


@router.get("", response_model=OrganizationOut)
def get_current_organization(
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    with session_scope() as session:
        _, org = require_org_membership(session, user_id, org_id)
        return OrganizationOut(
            id=str(org.id),
            name=org.name,
            is_personal=org.is_personal,
        )


@router.patch("")
def patch_organization(
    body: OrganizationPatchBody,
    user_id: UUID = Depends(get_current_user_id),
    org_id: UUID = Depends(get_current_org_id),
):
    new_name = body.name.strip()
    with session_scope() as session:
        _, org = require_org_membership(session, user_id, org_id)
        org.name = new_name
        session.commit()
    return {"status": "ok", "name": new_name}
