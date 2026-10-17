import time

from app.core.security import (
    constant_time_equals,
    derive_watch_secret,
    generate_api_key,
    hash_api_key,
    sign_webhook,
    verify_webhook_signature,
)


def test_generate_api_key_shape_and_hash():
    g = generate_api_key("pepper", env="test")
    assert g.raw_key.startswith("prv_test_") and len(g.raw_key) >= 50
    assert g.key_prefix == g.raw_key[:17]
    assert g.key_hash == hash_api_key(g.raw_key, "pepper")
    assert g.key_hash != hash_api_key(g.raw_key, "other-pepper")
    assert generate_api_key("pepper").raw_key != generate_api_key("pepper").raw_key


def test_constant_time_equals():
    assert constant_time_equals("abc", "abc") and not constant_time_equals("abc", "abd")


def test_webhook_signature_roundtrip():
    secret = derive_watch_secret("master", "watch-1")
    assert secret != derive_watch_secret("master", "watch-2")
    body = b'{"a":1}'
    ts = int(time.time())
    sig = sign_webhook(secret, ts, body)
    assert sig.startswith("v1=")
    assert verify_webhook_signature(secret, str(ts), sig, body)
    assert not verify_webhook_signature(secret, str(ts), sig, b'{"a":2}')
    assert not verify_webhook_signature("wrong", str(ts), sig, body)
    assert not verify_webhook_signature(
        secret, str(ts - 10_000), sign_webhook(secret, ts - 10_000, body), body
    )
    assert not verify_webhook_signature(secret, "nan", sig, body)
