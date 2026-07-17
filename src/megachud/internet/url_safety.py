from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

__all__ = ["UrlSafetyError", "check_url_safety", "ALLOWED_SCHEMES"]

ALLOWED_SCHEMES = {"http", "https"}


class UrlSafetyError(Exception):
    """Raised when a URL fails scheme, SSRF, or allow/deny-list checks.

    This is network-hygiene (private-address/scheme rejection), NOT a
    phishing or malicious-content detector. It cannot tell a legitimate
    site from a lookalike/scam domain — nothing in this codebase can, and
    it does not pretend to. It exists to stop the agent's HTTP tools from
    reaching loopback/internal/link-local network targets (SSRF), and
    from being pointed at non-HTTP(S) schemes.

    Known limitation, deliberately not closed here: this validates the
    resolved address BEFORE connecting. A DNS-rebinding attacker could
    change the answer between this check and the caller's actual
    connection (TOCTOU). Closing that needs a custom transport that pins
    the validated IP for the real socket connect — real, buildable, but
    more than this stage needs; a documented follow-up, not an oversight.
    """


def _resolve_hostname(hostname: str) -> list[str]:
    """Thin wrapper around socket.getaddrinfo — the sole seam tests
    monkeypatch to avoid a real DNS lookup. Also the thing that
    neutralizes numeric/hex/octal IP-obfuscation tricks (e.g.
    http://2130706433/), since getaddrinfo normalizes them to a real
    address before the ipaddress checks below ever run.
    """
    infos = socket.getaddrinfo(hostname, None)
    return sorted({info[4][0] for info in infos})


def _is_unsafe_ip(raw_ip: str) -> bool:
    ip = ipaddress.ip_address(raw_ip)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def check_url_safety(
    url: str,
    *,
    domain_allowlist: list[str] | None = None,
    domain_denylist: list[str] | None = None,
) -> None:
    """Validate `url` before a caller connects to it. Raises
    UrlSafetyError with a human-readable reason on any failure.

    Must be called again for EVERY redirect hop a caller follows —
    validating only the original URL and then blindly following
    redirects is a well-known SSRF bypass; this function intentionally
    has no "trust after first check" state.
    """
    parsed = urlsplit(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UrlSafetyError(f"scheme not allowed: {parsed.scheme!r} (only http/https)")

    hostname = parsed.hostname
    if not hostname:
        raise UrlSafetyError(f"URL has no hostname: {url!r}")

    for denied in domain_denylist or []:
        if hostname == denied or hostname.endswith(f".{denied}"):
            raise UrlSafetyError(f"domain is denylisted: {hostname!r}")

    if domain_allowlist:
        if not any(hostname == allowed or hostname.endswith(f".{allowed}") for allowed in domain_allowlist):
            raise UrlSafetyError(f"domain not in allowlist: {hostname!r}")

    try:
        resolved_ips = _resolve_hostname(hostname)
    except OSError as exc:
        raise UrlSafetyError(f"could not resolve hostname {hostname!r}: {exc}") from None

    if not resolved_ips:
        raise UrlSafetyError(f"hostname {hostname!r} did not resolve to any address")

    # Reject if ANY resolved address is unsafe — a hostname that
    # round-robins between a public IP and 127.0.0.1 must still fail.
    for raw_ip in resolved_ips:
        if _is_unsafe_ip(raw_ip):
            raise UrlSafetyError(f"URL resolves to a non-public address: {raw_ip}")
