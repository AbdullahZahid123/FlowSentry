"""FlowSentry API application assembly.

Brings together all routers, standard error envelopes, request-id and
security middleware, health endpoints, and the embedded worker lifecycle.
Run with: uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid as uuidlib
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import config, errors
from app.core.db import get_engine
from app.models.models import Base

logger = logging.getLogger("flowsentry.app")

APP_VERSION = "1.0.0"

_STATUS_TO_CODE = {
    400: "validation_error",
    401: "authentication_required",
    403: "permission_denied",
    404: "resource_not_found",
    405: "validation_error",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


def _init_database() -> bool:
    """Upgrade development databases; production schemas are migrated separately."""
    try:
        from app.core.migrations import upgrade_schema, current_revision, adopt_existing_schema
        from sqlalchemy import inspect
        if config.settings.app_env == "production":
            from alembic.script import ScriptDirectory
            from app.core.migrations import alembic_config
            return current_revision() == ScriptDirectory.from_config(alembic_config()).get_current_head()
        tables = inspect(get_engine()).get_table_names()
        if tables and "alembic_version" not in tables:
            adopt_existing_schema()
        upgrade_schema()
        return True
    except Exception:
        logger.warning("database schema is not ready; check migrations and database connectivity", exc_info=True)
        return False


async def _start_background() -> dict:
    from app.worker import start_worker_thread

    result: dict = {"worker": False, "db": False}
    result["db"] = await asyncio.to_thread(_init_database)
    if result["db"]:
        import threading
        stop_event = threading.Event()
        thread = await asyncio.to_thread(start_worker_thread, stop_event)
        result["worker_stop_event"] = stop_event
        result["worker_thread"] = thread
        result["worker"] = thread is not None
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = await _start_background()
    app.state.db_ready = state["db"]
    app.state.worker_stop_event = state.get("worker_stop_event")
    app.state.worker_thread = state.get("worker_thread")
    logger.info("startup: db_ready=%s worker=%s", state["db"], state["worker"])
    from app.modules import stream

    stream.ensure_tail_started()
    app.state.stream_tail = stream.tail_state.task
    try:
        yield
    finally:
        stop = getattr(app.state, "worker_stop_event", None)
        if stop is not None:
            stop.set()
        thread = getattr(app.state, "worker_thread", None)
        if thread is not None:
            await asyncio.to_thread(thread.join, config.settings.http_outbound_timeout_seconds + 2)
        tail = getattr(app.state, "stream_tail", None)
        if tail is not None and not tail.done():
            tail.cancel()


# APP_ROUTERS

def _register_routers(app: FastAPI) -> None:
    from app.modules import (
        analytics,
        audit_routes,
        auth,
        executions,
        incidents,
        ingest,
        integrations,
        notifications,
        stream,
        workflows,
)
    from app.modules.workspaces import router as workspaces_router

    app.include_router(auth.router)
    app.include_router(workspaces_router)
    app.include_router(integrations.router)
    app.include_router(workflows.router)
    app.include_router(executions.router)
    app.include_router(executions.recovery_router)
    app.include_router(incidents.router)
    app.include_router(notifications.router)
    app.include_router(notifications.rules_router)
    app.include_router(notifications.channels_router)
    app.include_router(notifications.notifications_router)
    app.include_router(analytics.router)
    app.include_router(audit_routes.router)
    app.include_router(ingest.router)
    app.include_router(stream.router)

def _register_health(app: FastAPI) -> None:
    @app.get("/health/live", summary="Liveness probe", tags=["health"])
    def health_live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", summary="Readiness probe", tags=["health"])
    async def health_ready() -> JSONResponse:
        ready = False
        try:
            engine = get_engine()

            def _check() -> bool:
                from sqlalchemy import text as _text

                with engine.connect() as conn:
                    conn.execute(_text("SELECT 1"))
                return True

            ready = bool(getattr(app.state, "db_ready", False)) and await asyncio.wait_for(asyncio.to_thread(_check), timeout=3.0)
        except Exception as e:
            logger.warning("readiness check failed: %s", e)
        if ready is False:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {"code": "service_unavailable", "message": "The service is not ready.", "details": []},
                    "meta": {"database": False, "worker": bool(getattr(app.state, "db_ready", False)) and config.settings.worker_enabled},
                },
            )
        return JSONResponse(content={"status": "ready", "database": True, "version": APP_VERSION})

    @app.get("/version", summary="Build information", tags=["health"])
    def version() -> dict:
        return {"data": {"name": config.settings.app_name, "version": APP_VERSION, "environment": config.settings.app_env}}

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"service": config.settings.app_name, "version": APP_VERSION, "docs": "/docs" if config.settings.app_env != "production" else None}


async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get(config.settings.request_id_header) or uuidlib.uuid4().hex
    request.state.request_id = rid
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error request_id=%s", rid)
        response = errors.error_response("service_unavailable", "The request could not be completed.", 503, None, rid)
    response.headers["X-Request-ID"] = rid
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("%s %s -> %s in %dms request_id=%s", request.method, request.url.path, response.status_code, elapsed_ms, rid)
    security = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin"}
    for name, value in security.items():
        response.headers.setdefault(name, value)
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    return response


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    code = _STATUS_TO_CODE.get(exc.status_code, "validation_error")
    detail = str(exc.detail) if exc.detail else "The request is invalid."
    return errors.error_response(code, detail, exc.status_code, None, rid)


def create_app() -> FastAPI:
    production = config.settings.app_env == "production"
    logging.basicConfig(level=config.settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(
        title=config.settings.app_name,
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[config.settings.csrf_header_name, "Authorization", "Content-Type", config.settings.request_id_header],
        expose_headers=[config.settings.request_id_header],
        max_age=600,
    )
    app.middleware("http")(request_id_middleware)
    _register_routers(app)
    _register_health(app)
    app.add_exception_handler(errors.ApiError, errors.api_error_handler)
    app.add_exception_handler(RequestValidationError, errors.validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, errors.unhandled_error_handler)
    return app


app = create_app()
