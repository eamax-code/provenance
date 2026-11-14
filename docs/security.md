# Security review before the pilot (GH #18)

Reviewed 2026-11-15. Each point is checked by a test in `tests/integration/test_security_headers.py`,
`tests/unit/test_ssrf.py` or `tests/unit/test_security.py` unless marked "owner".

## Browser
- **Headers on every response:** `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy`,
  `Permissions-Policy` (no camera, microphone, location or payment). In production,
  `Strict-Transport-Security` for a year (`app/core/security_headers.py`).
- **Content security policy:** scripts load only from this site. Inline scripts are allowed
  only by their SHA-256 hash, computed from the pages when the app starts, so an injected script
  never runs. Fonts load from Google Fonts. Pages cannot be framed (`frame-ancestors 'none'`)
  and no plugins load (`object-src 'none'`). Style attributes need `'unsafe-inline'` for
  styles only. Every page was loaded in Chrome with no policy violations.
- **No markup from data:** site scripts build the page with `textContent`. The only `innerHTML`
  writes clear a box or insert static markup from the same file, and a test enforces this.
- **CORS:** off by default; the API answers same-origin only. `CORS_ALLOW_ORIGINS` lists the
  origins allowed to call it from a browser, without credentials. Keys belong on a server.
- **Prototypes:** `/poc/` returns 404 in production.

## API
- **Keys:** stored as peppered hashes, shown once, revocable, never logged (AGENTS.md §7.5).
  Admin routes need `X-Admin-Token`, compared in constant time, and return 503 when no token is
  set.
- **Limits:** per-key and per-plan rate limits and monthly quotas. Per-address limits for the
  demo key and the public endpoints. Chat allows 10 questions a minute and 200 a day per key
  (per address for the demo key), because every answer can run a model.
- **Webhooks:** private, loopback, link-local and metadata addresses are refused when a watch is
  created, and again at delivery after DNS resolution. Redirects are not followed. Deliveries are
  signed with HMAC-SHA256 under a per-watch secret.
- **Errors:** one JSON envelope with a request ID; no stack traces, SQL or upstream bodies.

## Language model
- The model has no tools and cannot act. It sees filing text, figures and the question, and
  never sees keys, emails or configuration.
- Filing text, news headlines and the question are data. Each prompt tells the model to ignore
  instructions inside them, and every figure in an answer is checked against the cited data
  before it is shown.
- History sent by a client only affects that client's own answer.

## Dependencies
- `pip-audit` found no known vulnerabilities in the 45 pinned packages (2026-11-15), and it now
  runs in CI. Chart.js is vendored at 4.4.7 under `site/vendor/` and served from this site.

## Before launch (owner)
- Generate new `API_KEY_PEPPER`, `WEBHOOK_SIGNING_SECRET` and `ADMIN_TOKEN` for production;
  never reuse development values. Rotating the pepper invalidates every key, so do it before
  the first customer key.
- `--forwarded-allow-ips=*` is safe only while the app is reachable solely through the
  platform's proxy (Fly, Render). Do not expose the container port directly.
- Set `PUBLIC_BASE_URL` and `site/shell/site.json` to the chosen domain (ticket 02).
