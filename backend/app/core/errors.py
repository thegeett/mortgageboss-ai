"""Consistent, SAFE API error envelope + global exception handlers (LP-46).

Every error the API returns uses one envelope so the frontend has a single shape
to handle::

    {"error": {"type": str, "message": str, "details"?: [{"field", "message"}]}}

- ``type``    — a stable, machine-readable code (``not_found``, ``unauthorized``,
                ``validation_error``, ``internal_error``, …) the client can branch on.
- ``message`` — a SAFE, human-readable sentence. NEVER a stack trace, internal
                path, DB error text, or PII.
- ``details`` — present only for validation errors: which field, what's wrong.

**Safety is the whole point.** Unhandled exceptions become a generic 500 with a
safe message; the full detail is logged server-side as PII-safe *metadata*
(error type, request path/method, status — never request bodies, extracted
values, or PII). This protects internals (security) and borrower data (privacy).
"""

from typing import Any

import structlog
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

# Status code → stable error ``type``. Anything unmapped falls back to
# ``http_error`` (still a safe, consistent envelope).
_STATUS_TO_TYPE: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    422: "validation_error",  # Unprocessable Content (literal avoids a Starlette deprecation)
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}

_GENERIC_500_MESSAGE = "An unexpected error occurred. Please try again."


def error_body(
    type_: str, message: str, details: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Build the error envelope. ``details`` is included only when provided."""
    error: dict[str, Any] = {"type": type_, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Any uncaught exception → a SAFE generic 500. Full detail logged server-side.

    The client never sees the exception text (it could carry an internal path, a
    DB message, or PII). We log only metadata — the error *type* and the request
    path/method — never the request body or any value.
    """
    logger.error(
        "unhandled_exception",
        error_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body("internal_error", _GENERIC_500_MESSAGE),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """``HTTPException`` (404/401/403/400/409/…) → the envelope with its safe detail.

    Endpoint ``detail`` strings in this codebase are deliberately safe, generic
    messages ("Loan file not found", "Document not found"), so passing them
    through leaks nothing. The ``type`` is derived from the status code.
    """
    error_type = _STATUS_TO_TYPE.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(error_type, message),
        headers=headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """``RequestValidationError`` → 422 with field-level details in a consistent shape.

    Each detail is ``{"field": "loan_amount", "message": "..."}`` — the field
    path (minus the ``body``/``query`` location prefix) and Pydantic's message.
    Pydantic's messages describe the constraint, not the submitted value, so no
    user input is echoed back.
    """
    details: list[dict[str, str]] = []
    for err in exc.errors():
        location = err.get("loc", ())
        # Drop the leading location tag ("body"/"query"/"path") for a clean field path.
        parts = [str(p) for p in location[1:]] if len(location) > 1 else [str(p) for p in location]
        details.append({"field": ".".join(parts), "message": str(err.get("msg", "Invalid value"))})
    return JSONResponse(
        status_code=422,  # Unprocessable Content
        content=error_body("validation_error", "Some fields need your attention.", details),
    )


def register_exception_handlers(app: Any) -> None:
    """Wire the handlers onto the FastAPI app (called from ``app.main``).

    Order doesn't matter — FastAPI dispatches by exception type. The
    ``Exception`` handler is the catch-all backstop for anything uncaught.
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
