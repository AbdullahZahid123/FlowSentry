"""Request dependencies: sessions, CSRF, workspace authorization.

Every workspace-scoped dependency resolves the caller's active membership
from the session — never from a client-supplied claim (DATABASE.md 6.1).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session as OrmSession

from app.core import config
from app.core.db import get_session_factory
from app.core.errors import ApiError
from app.core.security import compare_digest, hash_token
from app.models.models import Session as DbSession
from app.models.models import User, WorkspaceMember

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2, "owner": 3}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db_session() -> OrmSession:
    db = get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _read_session_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(config.settings.session_cookie_name)
    return token


def resolve_session_user(db: OrmSession, request: Request, token: Optional[str] = None) -> User:
    """Shared cookie-session resolver. Request-scoped callers pass the token
    explicitly (e.g. the SSE stream, which releases the DB session before
    streaming)."""
    if token is None:
        token = _read_session_cookie(request)
    if not token:
        raise ApiError("authentication_required", "Authentication is required.", 401)
    token_hash = hash_token(token)
    row = db.execute(
        select(DbSession, User)
        .join(User, User.id == DbSession.user_id)
        .where(DbSession.token_hash == token_hash)
        .limit(1)
    ).first()
    if row is None:
        raise ApiError("authentication_required", "The session is invalid or expired.", 401)
    session_row, user = row
    from app.core.db import utcnow

    if session_row.revoked_at is not None or session_row.expires_at <= utcnow():
        raise ApiError("authentication_required", "The session is invalid or expired.", 401)
    if not user.is_active:
        raise ApiError("permission_denied", "This account is disabled.", 403)
    # touch last_seen (throttled by write only when >60s since last)
    if session_row.last_seen_at is None or (utcnow() - session_row.last_seen_at).total_seconds() > 60:
        session_row.last_seen_at = utcnow()
        db.add(session_row)
        db.flush()
    request.state.user = user
    return user


def get_current_user(request: Request, db: OrmSession = Depends(get_db_session)) -> User:
    return resolve_session_user(db, request)


def check_csrf(request: Request, user: User = Depends(get_current_user)) -> User:
    """Double-submit cookie CSRF protection for state-changing requests."""
    if request.method in SAFE_METHODS:
        return user
    cookie_token = request.cookies.get(config.settings.csrf_cookie_name)
    header_token = request.headers.get(config.settings.csrf_header_name)
    if not cookie_token or not header_token or not compare_digest(cookie_token, header_token):
        raise ApiError("csrf_required", "A valid CSRF token is required for this request.", 403)
    return user


def get_membership(
    workspace_id: uuid.UUID,
    request: Request,
    user: User = Depends(check_csrf),
    db: OrmSession = Depends(get_db_session),
) -> WorkspaceMember:
    member = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        # Not disclosing existence across workspaces (API_SPEC section 3)
        raise ApiError("resource_not_found", "The requested resource was not found.", 404)
    request.state.membership = member
    return member


def require_role(minimum_role: str):
    def checker(member: WorkspaceMember = Depends(get_membership)) -> WorkspaceMember:
        if ROLE_RANK[member.role] < ROLE_RANK[minimum_role]:
            raise ApiError("permission_denied", "Your role does not permit this action.", 403)
        return member

    return checker


def require_workspace_access(
    workspace_id: uuid.UUID, minimum_role: str, user: User, db: OrmSession
) -> WorkspaceMember:
    """Programmatic variant for services (worker paths, SSE auth)."""
    member = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise ApiError("resource_not_found", "The requested resource was not found.", 404)
    if ROLE_RANK[member.role] < ROLE_RANK[minimum_role]:
        raise ApiError("permission_denied", "Your role does not permit this action.", 403)
    return member


def system_status(db: OrmSession) -> dict:
    has_users = db.execute(text("SELECT EXISTS (SELECT 1 FROM users LIMIT 1)")).scalar()
    return {"needs_setup": not bool(has_users)}
