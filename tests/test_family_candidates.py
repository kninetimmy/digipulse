"""Tests for FAMILY_CANDIDATES / candidate_endpoints() -- per-family
targeting of candidate endpoints, and what one whole host actually costs a
sysop end to end.

The first live sample fired eight hypothesised paths at every host that
passed looks_like_dashboard(): 336 requests, 335 misses, and an access log
that reads like a vulnerability scan. The map under test replaces that with
"ask a host only for what hosts of its own family were observed to serve",
which for every family but one means asking for nothing.

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/ (that directory holds third-party bodies
whose redistribution is prohibited, and it is gitignored, so a test reading
it would fail on any machine that has not run a sweep). The fixtures below
carry only the marker each signature keys on, in invented wording.
Hostnames use the RFC 2606 reserved .test suffix so nothing resolves.
"""

import asyncio

import httpx
import pytest

import ysfprobe
from ysfprobe import (
    FAMILY_CANDIDATES,
    SIGNATURES,
    Prober,
    Reflector,
    candidate_endpoints,
    fingerprint,
)

TARGETED_FAMILY = "ysfdash-dg9vh"

# Minimal invented bodies carrying one signature marker each. Both are
# written to satisfy looks_like_dashboard() on their own terms too.
XLXD_BODY = (
    "<html><head><title>XLX999 Reflector Dashboard</title></head>"
    "<body>Connected modules and peers</body></html>"
)
DG9VH_BODY = (
    "<html><head><title>Synthetic YSFReflector-Dashboard</title></head>"
    "<body>Last heard list, gateways, callsigns</body></html>"
)
UNIDENTIFIED_BODY = (
    "<html><head><title>Synthetic Link Monitor</title></head>"
    "<body>reflector status page with a last heard mention</body></html>"
)


# ---------------------------------------------------------------------------
# The map itself
# ---------------------------------------------------------------------------


def test_the_one_observed_endpoint_is_registered_for_its_family():
    # lh.php on ysf.cq-nw.uk was the only non-error response in all 336
    # candidate requests of the first live sample. The response was a
    # 512-byte HTML fragment, not JSON, and its <tbody> was empty -- see
    # the block comment above FAMILY_CANDIDATES for both caveats.
    assert FAMILY_CANDIDATES[TARGETED_FAMILY] == ["lh.php"]


def test_every_other_observed_family_is_registered_with_no_endpoint_at_all():
    # Each of these was asked for all eight paths on every host of the
    # family and answered 404 to every one. No path has been observed to
    # work, so none is registered -- a plausible-looking guess is exactly
    # what this map exists to retire.
    for family in ("xlxd", "fusion-dashboard", "pysfreflector3", "ycs",
                   "mmdvm-generic", "wsysfdash"):
        assert FAMILY_CANDIDATES[family] == [], family


def test_a_fork_does_not_inherit_its_ancestors_endpoint():
    # ysfdash2-shaymez sits above ysfdash-dg9vh in SIGNATURES because it is
    # a fork of it, and it matched zero hosts in the sample -- so there is
    # no evidence either way about what it serves, and it gets nothing. The
    # sample also shows the inheritance assumption failing directly: the
    # wsysfdash hosts include one that still titles itself a DG9VH
    # dashboard, and lh.php 404'd on it.
    assert FAMILY_CANDIDATES["ysfdash2-shaymez"] == []
    assert candidate_endpoints("ysfdash2-shaymez") == []


def test_every_mapped_name_is_a_real_signature_family():
    # A typo in a key would silently disable targeting for that family
    # (candidate_endpoints() would never find it) while looking correct.
    known = {sig.family for sig in SIGNATURES}
    assert set(FAMILY_CANDIDATES) <= known, set(FAMILY_CANDIDATES) - known


def test_no_family_is_missing_from_the_map():
    # Not required for correctness -- an unmapped family already gets
    # nothing -- but it means adding a signature forces an explicit
    # "observed nothing, so nothing" decision rather than a silent default.
    assert {sig.family for sig in SIGNATURES} <= set(FAMILY_CANDIDATES)


# ---------------------------------------------------------------------------
# candidate_endpoints()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", [None, ""])
def test_a_host_with_no_family_gets_nothing(family):
    assert candidate_endpoints(family) == []


def test_a_family_absent_from_the_map_gets_nothing():
    # A signature added since the last sweep has no observations behind it.
    # The default must be silence, not the old eight-path guess list.
    assert candidate_endpoints("family-added-later") == []


def test_the_returned_list_cannot_be_mutated_into_the_map():
    endpoints = candidate_endpoints(TARGETED_FAMILY)
    endpoints.append("api.php")
    assert FAMILY_CANDIDATES[TARGETED_FAMILY] == ["lh.php"]


def test_fingerprint_and_the_map_agree_on_family_names():
    # The map is keyed on whatever fingerprint() returns; if the two ever
    # drift apart, targeting silently stops happening.
    assert candidate_endpoints(fingerprint(DG9VH_BODY)[0]) == ["lh.php"]
    assert candidate_endpoints(fingerprint(XLXD_BODY)[0]) == []


# ---------------------------------------------------------------------------
# End to end: what one host costs a sysop
# ---------------------------------------------------------------------------


def _probe_one(body, cache_dir, url="https://dash.example.test/"):
    """Probe one synthetic host and return (result, urls requested)."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == url:
            return httpx.Response(200, text=body,
                                  headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport,
                                     follow_redirects=True) as client:
            prober = Prober(client, asyncio.Semaphore(1), check_json=True,
                             respect_robots=False, cache_dir=str(cache_dir))
            ref = Reflector(ref_id="90101", name="Synthetic", description="",
                            host="dash.example.test", port=None, raw="",
                            url=url, dns="dash.example.test")
            return await prober.probe(ref)

    return asyncio.run(go()), requested


def test_a_family_with_no_registered_endpoint_costs_exactly_one_request(tmp_path):
    # 20 of the 43 hosts in the sample were xlxd, and each was asked for
    # eight paths that all 404'd -- 160 requests for nothing. One root
    # fetch is the whole footprint now.
    res, requested = _probe_one(XLXD_BODY, tmp_path)
    assert res.family == "xlxd"
    assert requested == ["https://dash.example.test/"]


def test_an_unidentified_host_costs_exactly_one_request(tmp_path):
    # No family, but enough dashboard-ish words that looks_like_dashboard()
    # says yes -- which under the old sweep was all it took to cost the
    # sysop eight requests.
    res, requested = _probe_one(UNIDENTIFIED_BODY, tmp_path)
    assert res.family is None
    assert ysfprobe.looks_like_dashboard(UNIDENTIFIED_BODY, None, res.title)
    assert requested == ["https://dash.example.test/"]


def test_the_targeted_family_costs_the_root_plus_its_one_endpoint(tmp_path):
    res, requested = _probe_one(DG9VH_BODY, tmp_path)
    assert res.family == TARGETED_FAMILY
    assert requested == [
        "https://dash.example.test/",
        "https://dash.example.test/lh.php",
    ]


def test_the_looks_like_dashboard_gate_is_still_consulted(tmp_path, monkeypatch):
    # Per-family targeting made this outer gate redundant in practice --
    # every host with a family already passes it -- but it is the
    # documented politeness contract and must still be able to stop the
    # candidate request. Forcing it false must silence even the one family
    # that has a registered endpoint.
    monkeypatch.setattr(ysfprobe, "looks_like_dashboard", lambda *a, **k: False)
    res, requested = _probe_one(DG9VH_BODY, tmp_path)
    assert res.family == TARGETED_FAMILY
    assert requested == ["https://dash.example.test/"]


def test_no_json_probe_still_suppresses_the_candidate_request(tmp_path):
    # --no-json-probe is the operator's kill switch for candidate requests;
    # per-family targeting must not have routed around it.
    requested: list[str] = []
    url = "https://dash.example.test/"

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text=DG9VH_BODY,
                              headers={"content-type": "text/html"})

    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport,
                                     follow_redirects=True) as client:
            prober = Prober(client, asyncio.Semaphore(1), check_json=False,
                             respect_robots=False, cache_dir=str(tmp_path))
            ref = Reflector(ref_id="90101", name="Synthetic", description="",
                            host="dash.example.test", port=None, raw="",
                            url=url, dns="dash.example.test")
            return await prober.probe(ref)

    res = asyncio.run(go())
    assert res.family == TARGETED_FAMILY
    assert requested == [url]
