"""Database engine, session factory, and shared helpers.

PostgreSQL is the system of record (ADR-002). The engine is created lazily so
that importing configuration does not require a reachable database.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core import config

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = make_url(config.settings.database_url)
        connect_args: dict[str, Any] = {}
        if url.get_backend_name() in ("postgresql", "postgres"):
            connect_args["connect_timeout"] = 5
        _engine = create_engine(
            config.settings.database_url,
            pool_pre_ping=True,
            pool_size=config.settings.db_pool_size,
            max_overflow=config.settings.db_max_overflow,
            echo=config.settings.db_echo,
            connect_args=connect_args,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionLocal


def session_scope() -> Session:
    return get_session_factory()()


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """Explicit transaction context; rollback on error, commit on success."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


def advisory_xact_lock(session: Session, key: str) -> Session:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key}
    )
    return session
