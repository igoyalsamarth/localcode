"""Workspaces (organizations): list, create, switch session, members, delete."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_current_org_id, get_current_user_id
from api.jwt_session import create_session_token
from api.user_org import require_org_membership, require_workspace_role
from db import session_scope
from logger import get_logger
from model.enums import MemberRole
from model.tables import Organization, OrganizationMember, User
from services.user_service import create_team_workspace, get_user_by_username

logger = get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: str
    name: str
    is_personal: bool
    role: MemberRole


class WorkspaceCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkspaceSwitchBody(BaseModel):
    workspace_id: UUID


class WorkspaceSwitchResponse(BaseModel):
    token: str


class MemberAddBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    role: MemberRole = MemberRole.user


class MemberOut(BaseModel):
    user_id: str
    username: str
    role: MemberRole


def _list_workspaces(session: Session, user_id: UUID) -> list[WorkspaceOut]:
    rows = session.execute(
        select(Organization, OrganizationMember.role)
        .join(OrganizationMember)
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.is_personal.desc(), Organization.name)
    ).all()
    return [
        WorkspaceOut(
            id=str(org.id),
            name=org.name,
            is_personal=org.is_personal,
            role=role,
        )
        for org, role in rows
    ]


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user_id: UUID = Depends(get_current_user_id)):
    with session_scope() as session:
        return _list_workspaces(session, user_id)


@router.post("", response_model=WorkspaceOut)
def create_workspace(
    body: WorkspaceCreateBody,
    user_id: UUID = Depends(get_current_user_id),
):
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        org = create_team_workspace(session, user, body.name)
        session.commit()
        return WorkspaceOut(
            id=str(org.id),
            name=org.name,
            is_personal=False,
            role=MemberRole.creator,
        )


@router.post("/switch", response_model=WorkspaceSwitchResponse)
def switch_workspace(
    body: WorkspaceSwitchBody,
    user_id: UUID = Depends(get_current_user_id),
):
    gh_login: str | None
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        require_org_membership(session, user_id, body.workspace_id)
        gh_login = user.github_login
        session.commit()

    try:
        token = create_session_token(
            user_id=user_id,
            org_id=body.workspace_id,
            github_login=gh_login,
        )
    except RuntimeError as e:
        logger.error("Cannot issue session JWT: %s", e)
        raise HTTPException(status_code=500, detail="JWT_SECRET is not configured") from e
    return WorkspaceSwitchResponse(token=token)


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    with session_scope() as session:
        _, org, member = require_org_membership(session, user_id, workspace_id)
        if org.is_personal:
            raise HTTPException(
                status_code=400,
                detail="Personal workspace cannot be deleted",
            )
        if org.created_by_user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Only the workspace creator can delete this workspace",
            )
        require_workspace_role(member, MemberRole.creator)
        session.delete(org)
        session.commit()
    return {"status": "deleted"}


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    workspace_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    with session_scope() as session:
        _, _, actor = require_org_membership(session, user_id, workspace_id)
        require_workspace_role(actor, MemberRole.admin)
        rows = session.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == workspace_id)
        ).all()
        return [
            MemberOut(
                user_id=str(m.user_id),
                username=u.username,
                role=m.role,
            )
            for m, u in rows
        ]


@router.post("/{workspace_id}/members", response_model=MemberOut)
def add_member(
    workspace_id: UUID,
    body: MemberAddBody,
    user_id: UUID = Depends(get_current_user_id),
):
    if body.role == MemberRole.creator:
        raise HTTPException(
            status_code=400,
            detail="Cannot invite someone as creator",
        )
    with session_scope() as session:
        _, org, actor = require_org_membership(session, user_id, workspace_id)
        require_workspace_role(actor, MemberRole.admin)

        target = get_user_by_username(session, body.username.strip())
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        existing = session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == workspace_id,
                OrganizationMember.user_id == target.id,
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="User is already a member")

        row = OrganizationMember(
            organization_id=workspace_id,
            user_id=target.id,
            role=body.role,
        )
        session.add(row)
        session.commit()
        return MemberOut(
            user_id=str(target.id),
            username=target.username,
            role=body.role,
        )


@router.delete("/{workspace_id}/members/{member_user_id}")
def remove_member(
    workspace_id: UUID,
    member_user_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
):
    with session_scope() as session:
        _, org, actor = require_org_membership(session, user_id, workspace_id)
        require_workspace_role(actor, MemberRole.admin)

        victim = session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == workspace_id,
                OrganizationMember.user_id == member_user_id,
            )
        ).scalar_one_or_none()
        if not victim:
            raise HTTPException(status_code=404, detail="Member not found")

        if victim.role == MemberRole.creator:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the workspace creator",
            )
        if actor.role == MemberRole.admin:
            if victim.role != MemberRole.user:
                raise HTTPException(
                    status_code=403,
                    detail="Admins can only remove users with the user role",
                )
        if victim.user_id == user_id:
            raise HTTPException(
                status_code=400,
                detail="You cannot remove yourself from this workspace",
            )

        session.delete(victim)
        session.commit()
    return {"status": "removed"}


class WorkspacePatchBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


@router.patch("/{workspace_id}")
def patch_workspace(
    workspace_id: UUID,
    body: WorkspacePatchBody,
    user_id: UUID = Depends(get_current_user_id),
):
    """Rename workspace (creator only)."""
    new_name = body.name.strip()
    with session_scope() as session:
        _, org, member = require_org_membership(session, user_id, workspace_id)
        require_workspace_role(member, MemberRole.creator)
        org.name = new_name
        session.commit()
    return {"status": "ok", "name": new_name}
