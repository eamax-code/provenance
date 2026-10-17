"""Outbound URL validation for webhook destinations (SSRF mitigation)."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "64:ff9b::/96",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]

_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")


class UnsafeDestination(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTarget:
    hostname: str
    port: int
    addresses: tuple[str, ...]


def is_ip_allowed(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    return not any(ip in net for net in _BLOCKED_NETWORKS)


def validate_webhook_url(url: str, allow_private: bool = False, require_https: bool = True) -> str:
    """Validate syntax/scheme/host of a webhook URL. Returns the normalized URL."""
    if not url or len(url) > 2048:
        raise UnsafeDestination("Webhook URL must be between 1 and 2048 characters.")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    allowed_schemes = {"https"} if require_https and not allow_private else {"https", "http"}
    if scheme not in allowed_schemes:
        raise UnsafeDestination("Webhook URL must use https.")
    if parts.username or parts.password:
        raise UnsafeDestination("Webhook URL must not contain credentials.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeDestination("Webhook URL must include a host.")
    if not allow_private:
        if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
            raise UnsafeDestination("Webhook host is not allowed.")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not is_ip_allowed(host):
            raise UnsafeDestination("Webhook host resolves to a disallowed address.")
    return url


def resolve_and_check(url: str, allow_private: bool = False) -> ResolvedTarget:
    """Resolve the URL host right before delivery and verify every address is public."""
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".")
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeDestination("Webhook host could not be resolved.") from exc
    addresses = tuple(sorted({info[4][0] for info in infos}))
    if not addresses:
        raise UnsafeDestination("Webhook host could not be resolved.")
    if not allow_private:
        for addr in addresses:
            if not is_ip_allowed(addr):
                raise UnsafeDestination("Webhook host resolves to a disallowed address.")
    return ResolvedTarget(hostname=host, port=port, addresses=addresses)
