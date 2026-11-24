"""robots.txt and sitemap.xml for the public site (GH #21)."""

from __future__ import annotations

from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, settings_dep
from app.core.config import Settings
from app.services import public as public_service

router = APIRouter(include_in_schema=False)

# Pages worth finding from a search engine, most important first.
SITEMAP_PAGES = (
    "/",
    "/developers/",
    "/docs/",
    "/companies/",
    "/search/",
    "/insiders/",
    "/managers/",
    "/chat/",
    "/listings/",
    "/playground/",
    "/status/",
    "/changelog/",
    "/contact/",
    "/ipos/",
    "/legal/terms/",
    "/legal/privacy/",
    "/legal/acceptable-use/",
    "/legal/data-sources/",
)
# Never indexed: the API itself, the MCP endpoint and the prototypes.
DISALLOW = ("/v1/", "/poc/", "/mcp")


def origin(request: Request, settings: Settings) -> str:
    return (settings.public_base_url or str(request.base_url)).rstrip("/")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request, settings: Settings = Depends(settings_dep)):
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {path}" for path in DISALLOW]
    lines += ["", f"Sitemap: {origin(request, settings)}/sitemap.xml", ""]
    return PlainTextResponse("\n".join(lines), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml")
def sitemap(
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    base = origin(request, settings)
    ciks, _ = public_service.cached(
        "sitemap:ciks", lambda: public_service.showcase_ciks(db, settings)
    )
    urls = [f"{base}{path}" for path in SITEMAP_PAGES]
    urls += [f"{base}/companies/{cik}" for cik in ciks]
    body = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    )
    return Response(
        xml,
        media_type="application/xml",
        headers={"Cache-Control": f"public, max-age={public_service.CACHE_TTL_SECONDS}"},
    )
