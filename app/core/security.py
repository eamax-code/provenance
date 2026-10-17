"""API key generation/hashing and webhook signing primitives.

- API keys: 32 random bytes, base64url. Only a peppered SHA-256 hash is stored.
- Webhook secrets: derived per watch from WEBHOOK_SIGNING_SECRET + watch id, so the
  raw secret is never stored; only its hash is kept for audit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

KEY_PREFIX = "prv"


@dataclass(frozen=True)
class GeneratedKey:
    raw_key: str
    key_prefix: str
    key_hash: str


def hash_api_key(raw_key: str, pepper: str) -> str:
    return hashlib.sha256((pepper + ":" + raw_key).encode("utf-8")).hexdigest()


def generate_api_key(pepper: str, env: str = "live") -> GeneratedKey:
    material = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    raw = f"{KEY_PREFIX}_{env}_{material}"
    prefix = raw[: len(KEY_PREFIX) + 1 + len(env) + 1 + 8]
    return GeneratedKey(raw_key=raw, key_prefix=prefix, key_hash=hash_api_key(raw, pepper))


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def derive_watch_secret(master_secret: str, watch_id: str) -> str:
    return hmac.new(
        master_secret.encode("utf-8"), f"watch:{watch_id}".encode(), hashlib.sha256
    ).hexdigest()


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def sign_webhook(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


def verify_webhook_signature(
    secret: str,
    timestamp_header: str,
    signature_header: str,
    body: bytes,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> bool:
    try:
        ts = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    current = now if now is not None else int(time.time())
    if abs(current - ts) > tolerance_seconds:
        return False
    expected = sign_webhook(secret, ts, body)
    return hmac.compare_digest(expected.encode("ascii"), (signature_header or "").encode("ascii"))
