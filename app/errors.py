"""Application error types + FastAPI exception handlers.

Every anticipated failure is raised as an ``AppError`` with an HTTP status and
a safe, user-facing message. A catch-all handler ensures an *unexpected*
failure returns a clean JSON 500 instead of leaking a traceback, and logs the
detail server-side.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("ct200")


class AppError(Exception):
    """Base class for anticipated, safe-to-surface failures."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ValidationError(AppError):
    status_code = 422


class IngestError(AppError):
    """Bad input to the ingestion pipeline (bad path, unreadable PDF, ...)."""

    status_code = 400


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ProviderError(AppError):
    """The LLM provider is misconfigured or unreachable."""

    status_code = 502


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("%s %s -> %s: %s", request.method, request.url.path,
                       exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error"},
        )
