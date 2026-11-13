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

from app.core.permissions import PermissionDeniedError

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
    type_: str,
    message: str,
    details: list[dict[str, str]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the error envelope. ``details`` and ``data`` are included only when provided.

    ``details`` is the per-FIELD list a validation error carries. ``data`` is a STRUCTURED PAYLOAD
    a refusal needs the caller to act on — LP-850's open-draft conflict is the first: the dialog
    has to name the draft, its contents and its age, and "Request failed" is not something a
    processor can answer.
    """
    error: dict[str, Any] = {"type": type_, "message": message}
    if details is not None:
        error["details"] = details
    if data is not None:
        error["data"] = data
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
    # LP-850 REVIEW — A DICT DETAIL USED TO BE DISCARDED HERE, and with it the entire refusal.
    # LP-850's three request routes raise `HTTPException(409, detail=DraftConflictPublic...)` so the
    # UI can render the open draft, its contents and its age without a second round trip. Every
    # assertion about that payload was written against the EXCEPTION OBJECT at the service layer,
    # so nothing noticed that the client received `{"type": "conflict", "message": "Request
    # failed"}` and none of the contents. A structured detail now travels as `error.data`; a string
    # detail behaves exactly as before.
    message = "Request failed"
    data: dict[str, Any] | None = None
    if isinstance(exc.detail, str):
        message = exc.detail
    elif isinstance(exc.detail, dict):
        data = exc.detail
        supplied = exc.detail.get("message")
        if isinstance(supplied, str) and supplied:
            message = supplied
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(error_type, message, data=data),
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


class UserRuleError(Exception):
    """A people-management rule refused the change (LP-MB-Admin-03).

    Each subclass carries its status and the sentence the admin reads; the handler below sends both
    in the standard envelope, so the People sheet shows the server's own words inline.
    """

    status_code: int = status.HTTP_409_CONFLICT
    message: str = "That change is not allowed."

    def __init__(self, message: str | None = None) -> None:
        # A subclass may need a sentence about this case (which role is missing); most use theirs.
        if message is not None:
            self.message = message
        super().__init__(self.message)


class SelfRoleChange(UserRuleError):
    """Nobody changes their own roles."""

    message = "You can't change your own roles"


class SelfDeactivation(UserRuleError):
    """Nobody deactivates themselves."""

    message = "You can't deactivate yourself"


class OwnerProtected(UserRuleError):
    """The owner cannot be deactivated or lose ADMIN from inside the app (ADR-440)."""

    message = "This is the account owner. Contact MortgageBoss to change their access."


class NoRoles(UserRuleError):
    """A person holds at least one role."""

    status_code = 422
    message = "A person needs at least one role"


class AlreadyOnTeam(UserRuleError):
    """The address is an active user of this company (LP-MB-Admin-04)."""

    message = "Already on your team"


class DeactivatedOnTeam(UserRuleError):
    """The address is an inactive user of this company: reactivate rather than invite."""

    message = "Deactivated — reactivate them from the People list"


class ForeignEmail(UserRuleError):
    """The address is a user of another company (ADR-444). Generic on purpose: the same body
    whatever that company is, and never its name."""

    message = "This address can't be invited; contact support"


class TooManyInvites(UserRuleError):
    """The company has the maximum number of open invitations."""

    message = "At most 50 open invitations"


class InviteThrottled(UserRuleError):
    """A link was (re)sent for this invitation less than a minute ago."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Try again in a minute"


class NotEligible(UserRuleError):
    """A person cannot take this team slot (LP-MB-Admin-05): not active, not in the file's company,
    or missing the slot's role. The sentence says which."""

    status_code = 422
    message = "This person can't be added to the team"


class LoanOfficerIsInternal(UserRuleError):
    """The file's loan officer is a user, so the text fields follow their account (LP-MB-Admin-05)."""

    status_code = 422
    message = "Change the loan officer on the Team card"


async def user_rule_handler(request: Request, exc: UserRuleError) -> JSONResponse:
    """A refused people-management change → its status and its own message."""
    error_type = _STATUS_TO_TYPE.get(exc.status_code, "http_error")
    return JSONResponse(status_code=exc.status_code, content=error_body(error_type, exc.message))


async def permission_denied_handler(request: Request, exc: PermissionDeniedError) -> JSONResponse:
    """A service's ``ensure`` refusal → the same 403 ``require_permission`` gives (ADR-442).

    The missing key is not named: the body matches the route-level refusal exactly.
    """
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=error_body("forbidden", "Insufficient permissions"),
    )


def register_exception_handlers(app: Any) -> None:
    """Wire the handlers onto the FastAPI app (called from ``app.main``).

    Order doesn't matter — FastAPI dispatches by exception type. The
    ``Exception`` handler is the catch-all backstop for anything uncaught.
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(PermissionDeniedError, permission_denied_handler)
    app.add_exception_handler(UserRuleError, user_rule_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
