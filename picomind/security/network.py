"""SSRF and private-network guards for web tools and shell commands."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)
_URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)


def _is_private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in network for network in _BLOCKED_NETWORKS)


def validate_url(url: str) -> tuple[bool, str]:
    """Validate scheme, host, and resolved addresses before a request."""

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, str(exc)
    if parsed.scheme not in {"http", "https"}:
        return False, "仅允许 http 和 https URL"
    if not parsed.hostname:
        return False, "URL 缺少主机名"
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return False, f"无法解析主机名：{parsed.hostname}"
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except ValueError:
            continue
        if _is_private(address):
            return False, f"已拦截私有或内部地址：{address}"
    return True, ""


def contains_internal_url(command: str) -> bool:
    """Return True when a shell command contains an internal URL."""

    for match in _URL_RE.finditer(command):
        ok, _ = validate_url(match.group(0))
        if not ok:
            return True
    return False
