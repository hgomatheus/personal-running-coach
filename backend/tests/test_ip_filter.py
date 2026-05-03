"""
Property-based tests for the IP filter middleware.

# Feature: personal-running-coach, Property 1: LAN IP filter rejects all public addresses

**Validates: Requirements 1.2**
"""

import ipaddress

from fastapi.testclient import TestClient
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.main import app

# ---------------------------------------------------------------------------
# RFC-1918 private address ranges (and localhost)
# ---------------------------------------------------------------------------

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
]


def _int_to_ipv4(n: int) -> str:
    """Convert a 32-bit integer to a dotted-decimal IPv4 string."""
    return str(ipaddress.IPv4Address(n))


def _is_routable_public(ip_str: str) -> bool:
    """
    Return True if the IP is a globally routable public address —
    i.e. NOT private, loopback, link-local, multicast, reserved, or unspecified.
    """
    addr = ipaddress.ip_address(ip_str)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# All 32-bit integers that map to valid IPv4 addresses
_all_ipv4_ints = st.integers(min_value=0, max_value=2**32 - 1)


@st.composite
def public_ipv4(draw) -> str:
    """
    Generate a random IPv4 address that is NOT in any RFC-1918 or localhost
    range (i.e. a globally routable public address).
    """
    ip_int = draw(_all_ipv4_ints)
    ip_str = _int_to_ipv4(ip_int)
    assume(_is_routable_public(ip_str))
    return ip_str


@st.composite
def private_ipv4(draw) -> str:
    """
    Generate a random IPv4 address that IS in an RFC-1918 or localhost range.
    Picks one of the four private networks at random, then picks a random host
    within that network.
    """
    network = draw(
        st.sampled_from(
            [
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("127.0.0.0/8"),
            ]
        )
    )
    network_int = int(network.network_address)
    broadcast_int = int(network.broadcast_address)
    offset = draw(st.integers(min_value=0, max_value=broadcast_int - network_int))
    return _int_to_ipv4(network_int + offset)


# ---------------------------------------------------------------------------
# Helper: build a TestClient that reports a specific IP as the client host
# ---------------------------------------------------------------------------

def _request_with_ip(ip: str, path: str = "/health") -> int:
    """
    Send a GET request to ``path`` with the ASGI scope's ``client`` field set
    to ``ip`` and return the HTTP status code.

    Starlette's TestClient does not expose a direct way to override the ASGI
    ``client`` scope field, so we wrap the ASGI app in a thin shim that
    replaces ``scope["client"]`` before the middleware sees it.
    """

    async def _scoped_app(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = dict(scope)
            scope["client"] = (ip, 12345)
        await app(scope, receive, send)

    with TestClient(_scoped_app, raise_server_exceptions=False) as client:
        response = client.get(path)
    return response.status_code


# ---------------------------------------------------------------------------
# Property 1a: Public IP addresses are rejected with HTTP 403
# ---------------------------------------------------------------------------

@given(ip=public_ipv4())
@settings(max_examples=100)
def test_public_ip_is_rejected_with_403(ip: str):
    """
    Property 1 (public side): For any IPv4 address outside RFC-1918 ranges,
    the IP filter middleware SHALL return HTTP 403.

    # Feature: personal-running-coach, Property 1: LAN IP filter rejects all public addresses
    **Validates: Requirements 1.2**
    """
    status = _request_with_ip(ip)
    assert status == 403, f"Expected 403 for public IP {ip!r}, got {status}"


# ---------------------------------------------------------------------------
# Property 1b: RFC-1918 / localhost addresses are NOT rejected with 403
# ---------------------------------------------------------------------------

@given(ip=private_ipv4())
@settings(max_examples=100)
def test_private_ip_is_not_rejected(ip: str):
    """
    Property 1 (private side): For any IPv4 address within RFC-1918 ranges
    (or localhost), the IP filter middleware SHALL NOT return HTTP 403.
    The request may receive any other status code from the actual endpoint.

    # Feature: personal-running-coach, Property 1: LAN IP filter rejects all public addresses
    **Validates: Requirements 1.2**
    """
    status = _request_with_ip(ip)
    assert status != 403, f"Expected non-403 for private IP {ip!r}, got {status}"
