"""FastAPI application factory."""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import (
    routes_companies,
    routes_developer,
    routes_exports,
    routes_key_requests,
    routes_markets,
    routes_notifications,
    routes_public,
    routes_screen,
    routes_stats,
)
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, log_event, request_id_var
from app.db.session import configure_engine, get_engine, session_factory
from app.services.usage import record_usage

logger = logging.getLogger("app.http")

DESCRIPTION = """
**Provenance** is a developer API for US public-company identity, SEC filings, normalized
XBRL financial facts, freshness tracking, filing notifications and bounded exports.

**Data source:** official SEC EDGAR endpoints (data.sec.gov, www.sec.gov). Every filing and
fact carries a `source_url` pointing at the SEC record it came from.

**Independence:** this service is independent and is not affiliated with or endorsed by the
U.S. Securities and Exchange Commission.

**Limitations:** no stock prices or market data; facts are limited to standard us-gaap tags
exposed by the SEC company-facts API; timestamps that the SEC does not provide are `null`;
coverage is limited to companies that have been ingested. Nothing here is investment advice.
Review the underlying filing before relying on a value.
"""


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = "req_" + secrets.token_hex(8)
        request.state.request_id = rid
        token = request_id_var.set(rid)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            request_id_var.reset(token)
            raise
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        route = request.scope.get("route")
        route_template = getattr(route, "path", request.url.path)
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id is not None:
            try:
                length = response.headers.get("content-length")
                db = session_factory()()
                try:
                    record_usage(
                        db,
                        api_key_id,
                        rid,
                        route_template,
                        response.status_code,
                        units=1,
                        response_bytes=int(length) if length else None,
                        export_rows=getattr(request.state, "export_rows", None),
                    )
                finally:
                    db.close()
            except Exception:  # noqa: BLE001 - metering must never break a response
                logger.exception("usage metering failed")
        log_event(
            logger,
            logging.INFO,
            "request",
            method=request.method,
            path=route_template,
            status=response.status_code,
            duration_ms=duration_ms,
            api_key=bool(api_key_id),
        )
        request_id_var.reset(token)
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_engine(settings.database_url)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    app.include_router(routes_companies.router)
    app.include_router(routes_notifications.router)
    app.include_router(routes_developer.router)
    app.include_router(routes_exports.router)
    app.include_router(routes_stats.router)
    app.include_router(routes_key_requests.router)
    app.include_router(routes_public.router)
    app.include_router(routes_markets.router)
    app.include_router(routes_screen.router)

    @app.get("/healthz", tags=["operations"], summary="Process liveness")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"], summary="Configuration and database readiness")
    def readyz(request: Request):
        problems = settings.validate_for_runtime()
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        ready = db_ok and not problems
        body = {
            "status": "ready" if ready else "not_ready",
            "database": "ok" if db_ok else "unavailable",
            "configuration": "ok" if not problems else problems,
            "email_notifications": "configured" if settings.email_configured else "not_configured",
        }
        return JSONResponse(status_code=200 if ready else 503, content=body)

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        components["ApiKeyAuth"] = {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        components["AdminToken"] = {"type": "apiKey", "in": "header", "name": "X-Admin-Token"}
        for path, methods in schema.get("paths", {}).items():
            for method in methods.values():
                if path.startswith("/v1/"):
                    if path in ("/v1/stats", "/v1/developer/key-requests") or path.startswith(
                        "/v1/public/"
                    ):
                        method["security"] = []
                    elif path == "/v1/developer/api-keys" and method.get("summary", "").startswith(
                        "Create"
                    ):
                        method["security"] = [{"AdminToken": []}]
                    else:
                        method["security"] = [{"ApiKeyAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    # Static marketing site (index.html, llms.txt). Mounted last so API routes win.
    site_dir = Path(__file__).resolve().parent.parent / "site"
    if site_dir.is_dir():
        company_page = site_dir / "company.html"

        @app.get("/companies/{cik}", include_in_schema=False, response_class=FileResponse)
        def public_company_page(cik: str):
            # Shareable URL; the page script reads the CIK from the path and calls the API.
            return FileResponse(company_page, media_type="text/html")

        app.mount("/", StaticFiles(directory=str(site_dir), html=True), name="site")
    return app


app = create_app()
