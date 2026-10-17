import pytest

from app.core.ssrf import UnsafeDestination, is_ip_allowed, resolve_and_check, validate_webhook_url


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.5.5",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::7f00:1",
        "224.0.0.1",
        "198.18.0.1",
    ],
)
def test_blocked_ips(ip):
    assert not is_ip_allowed(ip)


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"])
def test_allowed_ips(ip):
    assert is_ip_allowed(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://[::1]/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/",
        "https://foo.internal/x",
        "https://user:pw@example.com/",
        "ftp://example.com/",
        "",
        "https://",
        "https://" + "a" * 2050 + ".com",
    ],
)
def test_validate_rejects(url):
    with pytest.raises(UnsafeDestination):
        validate_webhook_url(url)


def test_validate_accepts_public_https():
    assert (
        validate_webhook_url("https://hooks.example.com/sec?x=1")
        == "https://hooks.example.com/sec?x=1"
    )


def test_dev_mode_allows_private_http():
    assert validate_webhook_url("http://127.0.0.1:8081/", allow_private=True)


def test_resolve_and_check_blocks_private_resolution(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(UnsafeDestination):
        resolve_and_check("https://rebind.example.com/hook")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    target = resolve_and_check("https://ok.example.com/hook")
    assert target.addresses == ("93.184.216.34",) and target.port == 443
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror())
    )
    with pytest.raises(UnsafeDestination):
        resolve_and_check("https://nx.example.com/")
