# ADR 0001: Webhook secrets are derived, not stored

**Status:** accepted (2026-10-17)

Per-watch secret = HMAC-SHA256(WEBHOOK_SIGNING_SECRET, "watch:<watch_id>"). Only the hash is persisted.
The raw secret is shown once at watch creation.

**Why:** signing needs the raw secret at delivery time; storing it would mean plaintext or an
encryption layer. Deriving it keeps the database free of raw secrets with no new dependency.

**Consequence:** rotating WEBHOOK_SIGNING_SECRET invalidates every watch secret; customers must recreate watches.
