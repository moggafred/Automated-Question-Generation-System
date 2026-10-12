"""Shared API helpers: dependency wiring and domain-error translation."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from errors import AQGError

logger = logging.getLogger("aqg.api")

#: Validation messages are surfaced verbatim because they name the exact field
#: the caller got wrong; everything else is kept generic.
_SAFE_VALIDATION_MESSAGES = {
    "greater_than_equal": "This value is below the minimum allowed.",
    "less_than_equal": "This value is above the maximum allowed.",
    "missing": "A required value was not supplied.",
    "string_too_short": "This value is too short.",
    "string_too_long": "This value is too long.",
}


def install_exception_handlers(app) -> None:
    """Registers handlers so domain errors become clean JSON and nothing leaks."""

    @app.exception_handler(AQGError)
    async def _handle_domain_error(_request, exc: AQGError) -> JSONResponse:  # noqa: ANN001
        # The technical cause is logged server-side only; the client gets a
        # safe, actionable message.
        logger.warning("Domain error %s: %s (detail=%s)", exc.error_code, exc.message, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request, exc: RequestValidationError) -> JSONResponse:  # noqa: ANN001
        """Renders FastAPI's validation payload in the platform error envelope."""
        fields: list[dict[str, Any]] = []
        for item in exc.errors():
            location = [str(part) for part in item.get("loc", []) if part != "body"]
            fields.append(
                {
                    "field": ".".join(location) or "request",
                    "message": _SAFE_VALIDATION_MESSAGES.get(
                        str(item.get("type", "")), "This value could not be accepted."
                    ),
                }
            )

        named = [field for field in fields if field["field"]]
        detail = (
            f"Please check: {', '.join(field['field'] for field in named)}."
            if named
            else "The request could not be processed."
        )

        logger.info("Request validation failed: %s", fields)
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "detail": detail, "fields": fields},
        )

    @app.exception_handler(HTTPException)
    async def _handle_http_exception(_request, exc: HTTPException) -> JSONResponse:  # noqa: ANN001
        detail = exc.detail
        if isinstance(detail, str):
            body = {"error": "http_error", "detail": detail}
        elif isinstance(detail, dict):
            body = detail
        else:  # pragma: no cover - FastAPI validation error payloads
            body = {"error": "validation_error", "detail": "The request could not be processed."}
        headers = getattr(exc, "headers", None)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request, exc: Exception) -> JSONResponse:  # noqa: ANN001
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": "Something went wrong on our side. Please try again.",
            },
        )


def safe_handler(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that logs and normalises unexpected failures for a handler.

    Used on handlers that do not raise through the FastAPI exception machinery
    (for example work awaited inside a try/except block).
    """

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except AQGError:
            raise
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - last-resort safety net
            logger.exception("Unhandled failure in %s: %s", getattr(func, "__name__", func), exc)
            raise HTTPException(
                status_code=500,
                detail="Something went wrong while processing your request.",
            ) from exc

    wrapper.__name__ = getattr(func, "__name__", "wrapper")
    wrapper.__doc__ = func.__doc__
    return wrapper


def not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail=message)