"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api import (
    routes_account,
    routes_chat,
    routes_companies,
    routes_developer,
    routes_events,
    routes_exports,
    routes_graph,
    routes_ipos,
    routes_key_requests,
    routes_listing_watches,
    routes_markets,
    routes_mcp,
    routes_notifications,
    routes_ownership,
    routes_public,
    routes_screen,
    routes_search,
    routes_site,
    routes_stats,
    routes_timeline,
    routes_type_watches,
    routes_watchlists,
)
from app.core import rate_limits
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, log_event, request_id_var
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import (
    configure_engine,
    control_session_factory,
    get_engine,
    session_factory,
)
from app.services import showcase_cache
from app.services.usage import record_usage

# The company page layouts; the first is the default.
COMPANY_LAYOUTS = ("snapshot", "report", "dossier")
COMPANY_LAYOUT_COOKIE = "company_layout"

logger = logging.getLogger("app.http")
MCP_CHANNEL_HEADER = "x-provenance-channel"

# Static files are not fingerprinted, so they are cached for an hour and then revalidated with
# their ETag; pages are always revalidated so a deploy shows at once (GH #21).
STATIC_MAX_AGE = 3600
STATIC_SUFFIXES = (".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff2", ".ico")


def cache_policy(path: str, content_type: str) -> str | None:
    """The Cache-Control for a site response that did not set its own; None for the API."""
    if path.startswith(("/v1/", "/mcp", "/openapi.json", "/healthz", "/readyz")):
        return None
    if path.lower().endswith(STATIC_SUFFIXES):
        return f"public, max-age={STATIC_MAX_AGE}, stale-while-revalidate=86400"
    if content_type.startswith("text/html"):
        return "no-cache"
    return None


DESCRIPTION = """
**Provenance** is a developer API for US public-company identity, SEC filings, normalized
XBRL financial facts, freshness tracking, filing notifications and bounded exports.

**Data source:** SEC EDGAR filings. Every filing and fact carries a `source_url` pointing at
the filing it came from.

**Independence:** this service is independent and is not affiliated with or endorsed by the
U.S. Securities and Exchange Commission.

**Limitations:** no stock prices or market data; facts are limited to standard us-gaap tags
reported in XBRL filings; timestamps that the SEC does not provide are `null`;
coverage is limited to companies that have been ingested. Nothing here is investment advice.
Review the underlying filing before relying on a value.
"""


async def _demo_capped(request: Request, response):
    """The demo key's limits on every response: at most demo_max_limit rows in a list, whatever
    the endpoint's default page size, and its rate limit stated in the headers."""
    settings = request.app.state.settings
    cap = settings.demo_max_limit
    if response.headers.get("content-type", "").startswith("application/json"):
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if (
            isinstance(data, dict)
            and isinstance(data.get("data"), list)
            and len(data["data"]) > cap
        ):
            data["data"] = data["data"][:cap]
            if isinstance(data.get("meta"), dict):
                data["meta"]["has_more"] = True
            body = json.dumps(data, separators=(",", ":"), default=str).encode()
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        response = Response(content=body, status_code=response.status_code, headers=headers,
                            media_type="application/json")  # fmt: skip
    response.headers["X-RateLimit-Limit"] = str(settings.demo_rate_limit_per_minute)
    return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = "req_" + secrets.token_hex(8)
        request.state.request_id = rid
        token = request_id_var.set(rid)
        started = time.monotonic()
        cacheable = request.app.state.settings.demo_key_enabled and showcase_cache.is_demo_read(
            request
        )
        hit = showcase_cache.get(request) if cacheable else None
        try:
            if hit is not None:  # a repeat keyless view: no handler, no demo counters
                response = Response(content=hit[0], status_code=200, headers=hit[1])
                response.headers["X-Cache"] = "hit"
            else:
                response = await call_next(request)
        except Exception:
            request_id_var.reset(token)
            raise
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        if hit is None and getattr(request.state, "demo", False):
            response = await _demo_capped(request, response)
            if cacheable and response.status_code == 200 and hasattr(response, "body"):
                showcase_cache.put(request, response.body, dict(response.headers))
                response.headers["X-Cache"] = "miss"
        response.headers["X-Request-ID"] = rid
        if "cache-control" not in response.headers:
            policy = cache_policy(request.url.path, response.headers.get("content-type", ""))
            if policy:
                response.headers["Cache-Control"] = policy
        route = request.scope.get("route")
        route_template = getattr(route, "path", request.url.path)
        if request.headers.get(MCP_CHANNEL_HEADER) == "mcp":
            route_template += " (mcp)"  # calls an agent made through the MCP server (GH #22)
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id is not None:
            try:
                length = response.headers.get("content-length")
                db = control_session_factory()()  # never waits behind request sessions
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
    rate_limits.configure(settings.rate_limit_store)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        docs_url=None,  # the reference is site/docs/, in the site's own layout
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    if settings.app_env != "test":  # public statistics refresh in the background (P-01)
        from app.services.stats import start_refresher

        start_refresher(session_factory(), settings)
    site_dir = Path(__file__).resolve().parent.parent / "site"
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)  # never compresses event streams
    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["X-API-Key", "Content-Type", "Last-Event-ID"],
            expose_headers=[
                "X-Request-ID",
                "Retry-After",
                "X-RateLimit-Limit",
                "X-RateLimit-Remaining",
            ],  # fmt: skip
            allow_credentials=False,
        )
    app.add_middleware(
        SecurityHeadersMiddleware,
        site=site_dir if site_dir.is_dir() else None,
        hsts=settings.is_production,
    )
    install_error_handlers(app, site_dir if site_dir.is_dir() else None)

    app.include_router(routes_companies.router)
    app.include_router(routes_graph.router)
    app.include_router(routes_ownership.router)
    app.include_router(routes_timeline.router)
    app.include_router(routes_watchlists.router)
    app.include_router(routes_ipos.router)
    app.include_router(routes_notifications.router)
    app.include_router(routes_listing_watches.router)
    app.include_router(routes_type_watches.router)
    app.include_router(routes_developer.router)
    app.include_router(routes_exports.router)
    app.include_router(routes_stats.router)
    app.include_router(routes_key_requests.router)
    app.include_router(routes_public.router)
    app.include_router(routes_markets.router)
    app.include_router(routes_events.router)
    app.include_router(routes_events.types_router)
    app.include_router(routes_chat.router)
    app.include_router(routes_screen.router)
    app.include_router(routes_search.router)
    app.include_router(routes_site.router)
    app.include_router(routes_mcp.router)
    app.include_router(routes_account.router)

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
        schema = None
        if db_ok:
            from app.db.schema_guard import problem as schema_problem

            schema = schema_problem(get_engine())
        ready = db_ok and not problems and not schema
        body = {
            "status": "ready" if ready else "not_ready",
            "database": "ok" if db_ok else "unavailable",
            "schema": "ok" if not schema else schema,
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
                        ("/v1/public/", "/v1/account")
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
    if site_dir.is_dir():
        layout_dir = site_dir / "companies" / "page"

        @app.get("/companies/{cik}", include_in_schema=False, response_class=HTMLResponse)
        def public_company_page(request: Request, cik: str, layout: str | None = None):
            # Shareable URL; the page script reads the CIK from the path and calls the API.
            # Snapshot is the page; ?layout= picks Report or Dossier and is remembered.
            if not (cik.isdigit() and len(cik) <= 10):
                raise StarletteHTTPException(status_code=404)  # browsers get the 404 page
            chosen = layout if layout in COMPANY_LAYOUTS else None
            remembered = request.cookies.get(COMPANY_LAYOUT_COOKIE)
            name = chosen or (remembered if remembered in COMPANY_LAYOUTS else COMPANY_LAYOUTS[0])
            page = (layout_dir / f"{name}.html").read_text(encoding="utf-8")
            try:  # a server-rendered head from stored data, for search and link previews
                from app.api.routes_site import origin as site_origin
                from app.services import seo
                from app.services.sec_client import normalize_cik as _norm

                db = session_factory()()
                try:
                    head = seo.head_for(db, settings, _norm(cik), site_origin(request, settings))
                finally:
                    db.close()
                page = seo.render(page, head)
            except Exception:  # noqa: BLE001 - the page still works with its generic head
                logger.exception("company page head failed")
            response = HTMLResponse(page)
            response.headers["Vary"] = "Cookie"
            if chosen:
                response.set_cookie(
                    COMPANY_LAYOUT_COOKIE,
                    chosen,
                    max_age=365 * 24 * 3600,
                    path="/companies",
                    samesite="lax",
                    httponly=True,
                )
            return response

        if settings.is_production:
            # the design prototypes are for review, never for visitors (GH #18)
            @app.get("/poc/{rest:path}", include_in_schema=False)
            def no_prototypes(rest: str):
                raise StarletteHTTPException(status_code=404)

        app.mount("/", StaticFiles(directory=str(site_dir), html=True), name="site")
    return app


app = create_app()
