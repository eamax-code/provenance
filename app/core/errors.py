"""Stable API error envelope. Internal details never reach clients."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}
        self.details = details  # additive, machine-readable (changes_not_available: reason)


def _envelope(request: Request, status: int, code: str, message: str, headers=None,
              details: dict | None = None):  # fmt: skip
    rid = getattr(request.state, "request_id", None)
    out_headers = {"X-Request-ID": rid} if rid else {}
    if headers:
        out_headers.update(headers)
    error = {"code": code, "message": message, "request_id": rid}
    if details:
        error.update(details)
    return JSONResponse(status_code=status, content={"error": error}, headers=out_headers)


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_parameter",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


# Paths that always answer in the JSON envelope, even to a browser.
API_PREFIXES = ("/v1/", "/openapi.json", "/healthz", "/readyz", "/mcp")


def _wants_page(request: Request) -> bool:
    """A browser asking for a page (not the API) gets the site's 404 and error pages."""
    path = request.url.path
    if path.startswith(API_PREFIXES) or request.method not in ("GET", "HEAD"):
        return False
    return "text/html" in request.headers.get("accept", "")


def install_error_handlers(app: FastAPI, pages: Path | None = None) -> None:
    """``pages`` is the static site; its not-found.html and error.html are served to browsers."""

    def _page(request: Request, status: int) -> FileResponse | None:
        if pages is None or not _wants_page(request):
            return None
        page = pages / ("not-found.html" if status == 404 else "error.html")
        if not page.is_file():
            return None
        rid = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": rid} if rid else {}
        headers["Cache-Control"] = "no-store"
        return FileResponse(page, status_code=status, media_type="text/html", headers=headers)

    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError):
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.headers, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p not in ("query", "body", "path"))
        msg = first.get("msg", "Invalid request")
        message = f"{loc}: {msg}" if loc else msg
        return _envelope(request, 422, "invalid_parameter", message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and (page := _page(request, 404)):
            return page
        code = _STATUS_CODES.get(exc.status_code, "error")
        detail = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        return _envelope(request, exc.status_code, code, detail, exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error", extra={"extra_fields": {"path": request.url.path}})
        if page := _page(request, 500):
            return page
        return _envelope(request, 500, "internal_error", "An internal error occurred.")
