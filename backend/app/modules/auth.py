"""Authentication: first-run owner setup, registration, login, logout,
session revocation, password reset (API_SPECIFICATION.md section 5)."""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession

from app.schemas.common import Timezone
from app.core import config
from app.core.db import utcnow, advisory_xact_lock
from app.core.errors import ApiError
from app.core.ratelimit import allow
from app.core.security import (
    hash_password,
    hash_token,
    new_session_token,
    verify_password,
)
from app.deps import check_csrf, get_current_user, get_db_session, system_status
from app.models.models import (
    Invitation,
    PasswordResetToken,
    Session as DbSession,
    User,
    Workspace,
    WorkspaceMember,
)
from app.modules import audit

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = config.settings.session_cookie_name
CSRF_COOKIE = config.settings.csrf_cookie_name


class SetupPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    workspace_name: str = Field(min_length=1, max_length=120)
    timezone: Timezone = "UTC"


class RegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)
    invitation_token: str | None = None


class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class AcceptInvitationPayload(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


class ForgotPayload(BaseModel):
    email: EmailStr


class ResetPayload(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


def _set_session_cookies(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.settings.session_lifetime_seconds,
        httponly=True,
        secure=config.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(24),
        max_age=config.settings.session_lifetime_seconds,
        httponly=False,  # double-submit: JS reads it to set the header
        secure=config.settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _start_session(db: OrmSession, user: User, request: Request) -> str:
    token = new_session_token()
    ua = request.headers.get("user-agent", "")[:300]
    sess = DbSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(seconds=config.settings.session_lifetime_seconds),
        last_seen_at=utcnow(),
        user_agent=ua,
    )
    db.add(sess)
    db.flush()
    return token


def _memberships(db: OrmSession, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(WorkspaceMember, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id)
        .where(Workspace.deleted_at.is_(None))
    ).all()
    return [
        {
            "workspace_id": str(m.workspace_id),
            "workspace_name": w.name,
            "workspace_slug": w.slug,
            "timezone": w.timezone,
            "role": m.role,
        }
        for m, w in rows
    ]


@router.get("/system-status")
def get_system_status(db: OrmSession = Depends(get_db_session)) -> dict:
    return system_status(db)


@router.post("/setup")
def first_run_setup(
    payload: SetupPayload, request: Request, response: Response, db: OrmSession = Depends(get_db_session)
) -> dict:
    advisory_xact_lock(db, "flowsentry:first-run-setup")
    if bool(db.execute(select(func.count(User.id))).scalar()):
        raise ApiError("conflict", "Setup has already been completed.", 409)
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        email_verified_at=utcnow(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(user)
    db.flush()
    workspace = Workspace(
        name=payload.workspace_name,
        slug=_slugify(db, payload.workspace_name),
        timezone=payload.timezone,
        created_by=user.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(workspace)
    db.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role="owner", joined_at=utcnow(), created_at=utcnow()
    )
    db.add(member)
    audit.record_audit(
        db,
        action="auth.setup_completed",
        resource_type="user",
        resource_id=user.id,
        workspace_id=workspace.id,
        actor_type="user",
        actor_id=user.id,
        request_id=request.state.request_id,
    )
    db.commit()
    token = _start_session(db, user, request)
    db.commit()
    _set_session_cookies(response, token)
    return {
        "data": {"user": _user_payload(user), "workspace": _workspace_payload(workspace, "owner")},
        "meta": {"request_id": request.state.request_id},
    }


@router.post("/register", status_code=201)
def register(
    payload: RegisterPayload,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db_session),
) -> dict:
    mode = config.settings.registration_mode
    invitation: Invitation | None = None
    if payload.invitation_token:
        token_hash = hash_token(payload.invitation_token)
        invitation = db.execute(
            select(Invitation).where(Invitation.token_hash == token_hash).with_for_update()
        ).scalar_one_or_none()
        if invitation is None or invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise ApiError("validation_error", "This invitation is invalid.", 422)
        if invitation.expires_at <= utcnow():
            raise ApiError("validation_error", "This invitation has expired.", 422)
        if str(invitation.email).lower() != payload.email.lower():
            raise ApiError("validation_error", "Use the email address this invitation was issued to.", 422)
        invitation_role = invitation.role
        invitation_email = str(invitation.email)
        invitation_workspace_id = invitation.workspace_id
    elif mode != "open":
        raise ApiError("permission_denied", "Registration requires a valid invitation.", 403)
    else:
        invitation_role = invitation_email = invitation_workspace_id = None

    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing is not None:
        raise ApiError("conflict", "An account with this email already exists.", 409)
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(user)
    db.flush()
    if invitation is not None:
        member = WorkspaceMember(
            workspace_id=invitation_workspace_id,
            user_id=user.id,
            role=invitation_role,
            joined_at=utcnow(),
            created_at=utcnow(),
        )
        db.add(member)
        invitation.accepted_at = utcnow()
        db.add(invitation)
        audit.record_audit(
            db,
            action="workspace.member_joined",
            resource_type="workspace",
            resource_id=invitation_workspace_id,
            workspace_id=invitation_workspace_id,
            actor_type="user",
            actor_id=user.id,
            request_id=request.state.request_id,
        )
    db.commit()
    token = _start_session(db, user, request)
    db.commit()
    _set_session_cookies(response, token)
    return {
        "data": {"user": _user_payload(user)},
        "meta": {"request_id": request.state.request_id},
    }


@router.post("/login")
def login(
    payload: LoginPayload, request: Request, response: Response, db: OrmSession = Depends(get_db_session)
) -> dict:
    ok, retry_after = allow(f"login:{payload.email.lower()}", limit=10, window_seconds=300)
    if not ok:
        raise ApiError("rate_limited", "Too many attempts. Try again later.", 429, headers={"Retry-After": str(retry_after)})
    ok_ip, retry_ip = allow(f"login-ip:{request.client.host if request.client else 'unknown'}", limit=30, window_seconds=300)
    if not ok_ip:
        raise ApiError("rate_limited", "Too many attempts. Try again later.", 429, headers={"Retry-After": str(retry_ip)})
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    generic = "Email or password is incorrect."
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise ApiError("authentication_required", generic, 401)
    if not user.is_active:
        raise ApiError("permission_denied", "This account is disabled.", 403)
    token = _start_session(db, user, request)
    db.commit()
    _set_session_cookies(response, token)
    return {
        "data": {"user": _user_payload(user), "memberships": _memberships(db, user.id)},
        "meta": {"request_id": request.state.request_id},
    }


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(check_csrf),
    db: OrmSession = Depends(get_db_session),
) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(
            update(DbSession)
            .where(DbSession.token_hash == hash_token(token))
            .values(revoked_at=utcnow())
        )
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return Response(status_code=204)


@router.get("/me")
def me(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db_session)) -> dict:
    return {
        "data": {"user": _user_payload(user), "memberships": _memberships(db, user.id)},
        "meta": {"request_id": None},
    }


@router.get("/sessions")
def list_sessions(request: Request, user: User = Depends(get_current_user), db: OrmSession = Depends(get_db_session)) -> dict:
    rows = db.execute(
        select(DbSession)
        .where(DbSession.user_id == user.id, DbSession.revoked_at.is_(None))
        .order_by(DbSession.created_at.desc())
        .limit(50)
    ).scalars().all()
    from app.core.db import utcnow as _now

    sessions = [
        {
            "id": str(s.id),
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
            "user_agent": s.user_agent,
            "current": s.token_hash == hash_token(request.cookies.get(config.settings.session_cookie_name, "")),
        }
        for s in rows
        if s.expires_at > _now()
    ]
    return {"data": sessions, "meta": {"request_id": None}}


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: uuid.UUID,
    user: User = Depends(check_csrf),
    db: OrmSession = Depends(get_db_session),
) -> None:
    row = db.execute(
        select(DbSession).where(DbSession.id == session_id, DbSession.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("resource_not_found", "Session not found.", 404)
    row.revoked_at = utcnow()
    db.add(row)
    db.commit()
    return Response(status_code=204)


# --- password reset ----------------------------------------------------------


@router.post("/forgot-password")
def forgot_password(payload: ForgotPayload, db: OrmSession = Depends(get_db_session)) -> dict:
    # Identical outward response whether or not the account exists (API_SPEC 5.5).
    ok, retry_after = allow(f"forgot:{payload.email.lower()}", limit=5, window_seconds=600)
    if not ok:
        raise ApiError("rate_limited", "Try again later.", 429, headers={"Retry-After": str(retry_after)})
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    token = None
    if user is not None:
        token = secrets.token_urlsafe(24)
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(minutes=30),
        )
        db.add(reset)
        db.commit()
        from app.modules.notify_send import send_notification_payload
        link = config.settings.frontend_url.rstrip("/") + "/login?reset=" + token
        delivered, _ = send_notification_payload("email", {"to": str(user.email)},
            "Reset your FlowSentry password", "Reset your password within 30 minutes: " + link)
        if not delivered:
            import logging
            logging.getLogger("flowsentry.auth").warning("password reset email delivery unavailable")
    return {"data": {"status": "sent"}, "meta": {"request_id": None}}


@router.post("/reset-password")
def reset_password(payload: ResetPayload, db: OrmSession = Depends(get_db_session)) -> dict:
    row = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token)
        ).with_for_update()
    ).scalar_one_or_none()
    generic = ApiError("validation_error", "This reset link is invalid or expired.", 422)
    if row is None:
        raise generic
    if row.used_at is not None or row.expires_at <= utcnow():
        raise generic
    user = db.execute(select(User).where(User.id == row.user_id)).scalar_one_or_none()
    if user is None:
        raise generic
    user.password_hash = hash_password(payload.password)
    user.updated_at = utcnow()
    row.used_at = utcnow()
    # revoke all sessions after password change
    db.execute(
        update(DbSession).where(DbSession.user_id == user.id).values(revoked_at=utcnow())
    )
    db.add(user)
    db.add(row)
    db.commit()
    return {"data": {"status": "reset"}, "meta": {"request_id": None}}


def _user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
    }


def _workspace_payload(w: Workspace, role: str) -> dict:
    return {
        "id": str(w.id),
        "name": w.name,
        "slug": w.slug,
        "timezone": w.timezone,
        "role": role,
    }


def _slugify(db: OrmSession, name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "workspace"
    slug = base[:60]
    n = 1
    while db.execute(select(Workspace.id).where(Workspace.slug == slug)).scalar_one_or_none() is not None:
        n += 1
        slug = f"{base[:50]}-{n}"
    return slug
