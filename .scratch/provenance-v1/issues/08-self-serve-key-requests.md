# 08: Self-serve key requests with abuse controls

**What to build:** A visitor requests a free key from the landing page or app; the request is recorded with abuse controls, an operator approves it with one command (or it is auto-approved when email delivery is configured and the address is verified), and the requester receives the key once.

**Blocked by:** 05

**Status:** done

- [x] `POST /v1/developer/key-requests` unauthenticated, per-IP rate limited, honeypot field, email validation, dedupe per email
- [x] `scripts/approve_key_request.py` issues the key and prints it, or emails it when SMTP is configured
- [x] Landing page and app have a request form with clear success/failure states
- [x] Tests cover rate limiting, duplicates and approval
