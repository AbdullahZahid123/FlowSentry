"""Workspace and membership endpoints (API_SPECIFICATION.md section 6)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session as OrmSession

from app.core.db import utcnow
from app.core.errors import ApiError
from app.core.security import hash_token, new_session_token
from app.deps import (
    ROLE_RANK,
    check_csrf,
    get_current_user,
    get_db_session,
    get_membership,
    require_role,
)
from app.models.models import Invitation, User, Workspace, WorkspaceMember
from app.modules import audit
from app.schemas.common import InvitationCreate, MemberRoleUpdate, WorkspaceCreate, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _workspace_payload(w: Workspace, role: str) -> dict:
    return {"id": str(w.id), "name": w.name, "slug": w.slug, "timezone": w.timezone, "role": role}


@router.get("")
def list_workspaces(
    user: User = Depends(get_current_user), db: OrmSession = Depends(get_db_session)
) -> dict:
    rows = (
        db.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == user.id)
            .where(Workspace.deleted_at.is_(None))
        )
        .all()
    )
    return {
        "data": [_workspace_payload(w, m.role) for m, w in rows],
        "meta": {"request_id": None, "next_cursor": None, "has_more": False},
    }


@router.post("", status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    request: Request,
    user: User = Depends(check_csrf),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    from app.modules.auth import _slugify

    workspace = Workspace(
        name=payload.name,
        slug=_slugify(db, payload.name),
        timezone=payload.timezone,
        created_by=user.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="owner",
            joined_at=utcnow(),
            created_at=utcnow(),
        )
    )
    audit.record_audit(
        db,
        action="workspace.created",
        resource_type="workspace",
        resource_id=workspace.id,
        workspace_id=workspace.id,
        actor_id=user.id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _workspace_payload(workspace, "owner"), "meta": {"request_id": request.state.request_id}}


@router.get("/{workspace_id}")
def get_workspace(
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    w = db.execute(select(Workspace).where(Workspace.id == member.workspace_id)).scalar_one()
    count = db.execute(
        select(WorkspaceMember.id).where(WorkspaceMember.workspace_id == w.id).limit(1000)
    ).all()
    return {"data": {**_workspace_payload(w, member.role), "member_count": len(count)}, "meta": {"request_id": None}}


@router.patch("/{workspace_id}")
def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    w = db.execute(select(Workspace).where(Workspace.id == workspace_id)).scalar_one()
    if payload.name is not None:
        w.name = payload.name
    if payload.timezone is not None:
        w.timezone = payload.timezone
    w.updated_at = utcnow()
    db.add(w)
    audit.record_audit(
        db,
        action="workspace.updated",
        resource_type="workspace",
        resource_id=workspace_id,
        workspace_id=workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {"data": _workspace_payload(w, member.role), "meta": {"request_id": request.state.request_id}}


@router.get("/{workspace_id}/members")
def list_members(
    workspace_id: uuid.UUID,
    member: WorkspaceMember = Depends(get_membership),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    rows = (
        db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.joined_at)
        )
        .all()
    )
    members = [
        {
            "user_id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role": m.role,
            "joined_at": m.joined_at.isoformat(),
        }
        for m, u in rows
    ]
    return {"data": members, "meta": {"request_id": None}}


@router.post("/{workspace_id}/invitations", status_code=201)
def create_invitation(
    workspace_id: uuid.UUID,
    payload: InvitationCreate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    token = new_session_token()
    inv = Invitation(
        workspace_id=workspace_id,
        email=payload.email.lower(),
        role=payload.role,
        token_hash=hash_token(token),
        created_by=member.user_id,
        expires_at=utcnow() + timedelta(days=7),
        created_at=utcnow(),
    )
    db.add(inv)
    audit.record_audit(
        db,
        action="workspace.invitation_created",
        resource_type="invitation",
        resource_id=inv.id,
        workspace_id=workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"email": payload.email, "role": payload.role},
    )
    db.commit()
    return {
        "data": {
            "id": str(inv.id),
            "email": str(inv.email),
            "role": inv.role,
            "expires_at": inv.expires_at.isoformat(),
            "token_once": token,
        },
        "meta": {"request_id": request.state.request_id},
    }


@router.get("/{workspace_id}/invitations")
def list_invitations(
    workspace_id: uuid.UUID,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    rows = db.execute(select(Invitation).where(
        Invitation.workspace_id == member.workspace_id,
        Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
        Invitation.expires_at > utcnow(),
    ).order_by(Invitation.created_at.desc()).limit(100)).scalars().all()
    return {"data": [{"id": str(i.id), "email": str(i.email), "role": i.role,
        "expires_at": i.expires_at.isoformat()} for i in rows], "meta": {"request_id": None}}


@router.patch("/{workspace_id}/members/{user_id}")
def update_member_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> dict:
    target = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ApiError("resource_not_found", "Member not found.", 404)
    if payload.role == "owner" and member.role != "owner":
        raise ApiError("permission_denied", "Only an owner can grant ownership.", 403)
    if target.role == "owner" and member.role != "owner":
        raise ApiError("permission_denied", "Only an owner can modify another owner.", 403)
    if target.role == "owner" and payload.role != "owner":
        _ensure_not_last_owner(db, workspace_id, user_id)
    target.role = payload.role
    db.add(target)
    audit.record_audit(
        db,
        action="workspace.member_role_changed",
        resource_type="user",
        resource_id=user_id,
        workspace_id=workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
        metadata={"role": payload.role},
    )
    db.commit()
    return {"data": {"user_id": str(user_id), "role": payload.role}, "meta": {"request_id": request.state.request_id}}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    member: WorkspaceMember = Depends(require_role("admin")),
    db: OrmSession = Depends(get_db_session),
) -> None:
    target = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if target is None:
        raise ApiError("resource_not_found", "Member not found.", 404)
    if target.role == "owner":
        if member.role != "owner":
            raise ApiError("permission_denied", "Only an owner can remove another owner.", 403)
        _ensure_not_last_owner(db, workspace_id, user_id)
    db.delete(target)
    audit.record_audit(
        db,
        action="workspace.member_removed",
        resource_type="user",
        resource_id=user_id,
        workspace_id=workspace_id,
        actor_id=member.user_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return Response(status_code=204)


def _ensure_not_last_owner(db: OrmSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.execute(select(Workspace).where(Workspace.id == workspace_id).with_for_update()).scalar_one()
    owners = db.execute(
        select(WorkspaceMember.user_id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == "owner",
        )
    ).all()
    owner_ids = [r[0] for r in owners]
    if len(owner_ids) <= 1 and user_id in owner_ids:
        raise ApiError(
            "conflict",
            "The last owner cannot be removed or demoted. Transfer ownership first.",
            409,
        )
