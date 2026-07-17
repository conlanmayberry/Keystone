from __future__ import annotations

import pytest

from megachud.internet import url_safety
from megachud.internet.url_safety import UrlSafetyError, check_url_safety


def _stub_resolver(monkeypatch, ip_map: dict[str, list[str]]):
    def fake_resolve(hostname: str) -> list[str]:
        return ip_map[hostname]

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)


def test_public_ip_passes(monkeypatch):
    _stub_resolver(monkeypatch, {"example.com": ["93.184.216.34"]})
    check_url_safety("https://example.com/page")


@pytest.mark.parametrize("scheme_url", ["file:///etc/passwd", "javascript:alert(1)", "data:text/plain,hi", "ftp://example.com/"])
def test_disallowed_scheme_rejected(scheme_url):
    with pytest.raises(UrlSafetyError, match="scheme not allowed"):
        check_url_safety(scheme_url)


def test_missing_hostname_rejected():
    with pytest.raises(UrlSafetyError, match="no hostname"):
        check_url_safety("https:///path")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # private
        "192.168.1.1",     # private
        "169.254.169.254", # link-local (cloud metadata endpoint)
        "::1",             # loopback v6
        "224.0.0.1",       # multicast
        "0.0.0.0",         # unspecified
    ],
)
def test_unsafe_resolved_address_rejected(monkeypatch, ip):
    _stub_resolver(monkeypatch, {"evil.example": [ip]})
    with pytest.raises(UrlSafetyError, match="non-public address"):
        check_url_safety("http://evil.example/")


def test_any_unsafe_address_in_multi_answer_rejects_whole_hostname(monkeypatch):
    # Round-robin DNS: one public answer, one private — must still reject.
    _stub_resolver(monkeypatch, {"mixed.example": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(UrlSafetyError, match="non-public address"):
        check_url_safety("http://mixed.example/")


def test_numeric_ip_literal_obfuscation_rejected(monkeypatch):
    # http://2130706433/ is the decimal encoding of 127.0.0.1 — getaddrinfo
    # normalizes this to a real address before the ipaddress check runs,
    # so it can't slip past as a string-matching bypass.
    _stub_resolver(monkeypatch, {"2130706433": ["127.0.0.1"]})
    with pytest.raises(UrlSafetyError, match="non-public address"):
        check_url_safety("http://2130706433/")


def test_denylisted_domain_rejected(monkeypatch):
    _stub_resolver(monkeypatch, {"blocked.example": ["93.184.216.34"]})
    with pytest.raises(UrlSafetyError, match="denylisted"):
        check_url_safety("https://blocked.example/", domain_denylist=["blocked.example"])


def test_denylist_matches_subdomains(monkeypatch):
    _stub_resolver(monkeypatch, {"sub.blocked.example": ["93.184.216.34"]})
    with pytest.raises(UrlSafetyError, match="denylisted"):
        check_url_safety("https://sub.blocked.example/", domain_denylist=["blocked.example"])


def test_allowlist_blocks_non_matching_domain(monkeypatch):
    _stub_resolver(monkeypatch, {"other.example": ["93.184.216.34"]})
    with pytest.raises(UrlSafetyError, match="not in allowlist"):
        check_url_safety("https://other.example/", domain_allowlist=["trusted.example"])


def test_allowlist_permits_matching_domain(monkeypatch):
    _stub_resolver(monkeypatch, {"trusted.example": ["93.184.216.34"]})
    check_url_safety("https://trusted.example/", domain_allowlist=["trusted.example"])


def test_empty_allowlist_is_unrestricted(monkeypatch):
    _stub_resolver(monkeypatch, {"anywhere.example": ["93.184.216.34"]})
    check_url_safety("https://anywhere.example/", domain_allowlist=[])


def test_dns_resolution_failure_rejected(monkeypatch):
    def fake_resolve(hostname: str) -> list[str]:
        raise OSError("name or service not known")

    monkeypatch.setattr(url_safety, "_resolve_hostname", fake_resolve)
    with pytest.raises(UrlSafetyError, match="could not resolve"):
        check_url_safety("https://nonexistent.example/")
