"""Tests for candidate_urls() -- what gets probed for a given Reflector."""

from fixtures import SYNTHETIC_JSON_EXPORT
from ysfprobe import Reflector, candidate_urls, parse_hosts_json


def _reflector(**overrides):
    base = dict(
        ref_id="1", name="n", description="d", host="h", port=None, raw="",
    )
    base.update(overrides)
    return Reflector(**base)


def test_declared_url_is_preferred_and_returned_alone():
    ref = _reflector(
        host="dash.example.test",
        url="https://dash.example.test/status",
        dns="dash.example.test",
    )
    assert candidate_urls(ref) == ["https://dash.example.test/status"]


def test_dns_hostname_falls_back_to_https_then_http():
    ref = _reflector(host="reflector.example.test", url=None, dns="reflector.example.test")
    assert candidate_urls(ref) == [
        "https://reflector.example.test/",
        "http://reflector.example.test/",
    ]


def test_bare_ip_only_record_yields_empty_list():
    # No declared url and no usable hostname: a bare IP can't carry a Host
    # header the reflector's vhost recognises, so probing it would hit a
    # default site, cost the sysop a request, and tell us nothing. This is
    # a deliberate skip, not a failure -- candidate_urls() must return [].
    ref = _reflector(host="203.0.113.13", url=None, dns=None)
    assert candidate_urls(ref) == []


def test_ip_only_registry_record_is_unmeasurable_end_to_end():
    reflectors, _ = parse_hosts_json(SYNTHETIC_JSON_EXPORT)
    ip_only = next(r for r in reflectors if r.ref_id == "90103")
    assert candidate_urls(ip_only) == []
