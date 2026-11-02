"""Standard API error envelope and exception types.

Every error follows API_SPECIFICATION.md section 2.8 and maps to the error
code registry in section 16.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ERROR_CODES = {
    "validation_error": 422,
    "authentication_required": 401,
    "permission_denied": 403,
    "resource_not_found": 404,
    "conflict": 409,
    "capability_not_supported": 409,
    "integration_unavailable": 502,
    "integration_auth_failed": 502,
    "rate_limited": 429,
    "idempotency_conflict": 409,
    "operation_in_progress": 409,
    "payload_too_large": 413,
    "unsupported_media_type": 415,
    "service_unavailable": 503,
    "csrf_required": 403,
}


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: Optional[int] = None,
        details: Optional[list[dict[str, Any]]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or ERROR_CODES.get(code, 400)
        self.details = details or []
        self.headers = headers


def error_response(
    code: str,
    message: str,
    status: int,
    details: Optional[list[dict[str, Any]]] = None,
    request_id: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "details": details or []},
        "meta": {"request_id": request_id},
    }
    return JSONResponse(status_code=status, content=body, headers=headers)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return error_response(
        exc.code, exc.message, exc.status, exc.details, request_id, exc.headers
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    details = []
    for err in exc.errors()[:20]:
        field = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        details.append({"field": field, "issue": err.get("msg", "Invalid value")})
    return error_response(
        "validation_error", "The request is invalid.", 422, details, request_id
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging

    logging.getLogger("flowsentry.error").exception(
        "Unhandled error request_id=%s", getattr(request.state, "request_id", None)
    )
    request_id = getattr(request.state, "request_id", None)
    return error_response(
        "service_unavailable",
        "The request could not be completed.",
        503,
        None,
        request_id,
    )
