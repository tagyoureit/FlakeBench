"""
Centralized API error handling helpers.

Goal: prevent Snowflake connectivity issues (VPN / network policy / IP allowlist)
from being misrepresented in the UI as "no results".
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApiError:
    status_code: int
    code: str
    message: str
    hint: str | None = None
    debug: str | None = None


def _maybe_debug(exc: BaseException) -> str | None:
    if settings.APP_DEBUG:
        return str(exc)
    return None


def classify_snowflake_error(exc: BaseException) -> ApiError | None:
    """
    Classify Snowflake connector failures into user-actionable errors.

    This intentionally uses string matching because upstream exception types can
    vary (OperationalError/DatabaseError) and many callers currently wrap
    exceptions before they reach the API layer.
    """

    msg = str(exc)
    lower = msg.lower()

    # Snowflake network policy / VPN / IP allowlist failure.
    if ("ip/token" in lower and "not allowed" in lower) or (
        "is not allowed to access snowflake" in lower
    ):
        return ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="SNOWFLAKE_IP_NOT_ALLOWED",
            message="Snowflake access blocked by network policy (VPN / IP allowlist).",
            hint="Connect to your VPN (or allowlist your current IP in Snowflake), then retry.",
            debug=_maybe_debug(exc),
        )

    # Generic connection failure (covers many 08001 cases).
    if "failed to connect to db" in lower or "(08001)" in lower:
        return ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="SNOWFLAKE_CONNECTION_FAILED",
            message="Failed to connect to Snowflake.",
            hint="Check VPN/network access and Snowflake account URL, then retry.",
            debug=_maybe_debug(exc),
        )

    return None


def http_exception(operation: str, exc: BaseException) -> HTTPException:
    """
    Convert an exception into a consistent HTTPException payload.
    """
    # Log the full traceback to the server console for debugging
    logger.error(
        "API error during '%s': %s\n%s",
        operation,
        exc,
        traceback.format_exc(),
    )

    sf = classify_snowflake_error(exc)
    if sf is not None:
        detail: dict[str, Any] = {
            "code": sf.code,
            "message": sf.message,
            "operation": operation,
        }
        if sf.hint:
            detail["hint"] = sf.hint
        if sf.debug:
            detail["debug"] = sf.debug
        return HTTPException(status_code=sf.status_code, detail=detail)

    # Default: preserve a safe summary + optional debug.
    base_detail: dict[str, Any] = {
        "code": "INTERNAL_ERROR",
        "message": f"{operation} failed.",
        "operation": operation,
    }
    dbg = _maybe_debug(exc)
    if dbg:
        base_detail["debug"] = dbg
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=base_detail,
    )
