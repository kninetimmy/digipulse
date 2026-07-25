"""Tests for Prober.probe_json() -- which paths a host is asked for, and
that whatever comes back is cached with its HTTP status recoverable offline
from the cache alone (PR #13 review, required fix 1).

Two things are under test here. First, targeting: probe_json() no longer
fires a fixed eight-path list at every host that looks like a dashboard, it
asks a host only for the paths registered for its own fingerprinted family
(FAMILY_CANDIDATES), and a family with no registered path is asked for
nothing at all. Second, labelling: a 404 on a registered endpoint and a 200
carrying a real body used to write byte-indistinguishable cache entries, so
an analyst globbing json-*.gz could not tell them apart without re-fetching
from the sysop.

Every body below is invented for this test; none of it is real dashboard
HTML copied from ysfprobe_cache/. Uses httpx.MockTransport so no network
access happens anywhere in this file, and hostnames use the RFC 2606
reserved .test suffix so nothing here resolves even by accident. This
project's test suite has no async plugin configured, so each async call is
driven through asyncio.run() from an ordinary sync test.
"""

import asyncio

import httpx

from ysfprobe import (
    FAMILY_CANDIDATES,
    ProbeResult,
    Prober,
    cache_key,
    cache_response,
    read_cached_response,
)

# The one family the first live sample gave an observed endpoint, and the
# one path registered for it. Read from the map rather than hardcoded, so
# these tests keep testing the real registration instead of a stale copy.
TARGETED_FAMILY = "ysfdash-dg9vh"
TARGETED_PATH = FAMILY_CANDIDATES[TARGETED_FAMILY][0]

# Shaped like the observed last-heard fragment -- an HTML fragment, not
# JSON -- but written from scratch with invented wording.
SYNTHETIC_FRAGMENT = (
    '<div class="card"><div class="card-header">Heard List</div>'
    '<table id="lh"><thead><tr><th>Time</th><th>Callsign</th></tr></thead>'
    "<tbody></tbody></table></div>"
)


def _run_probe_json(handler, cache_dir, family, base="https://dash.example.test/"):
    """Drive probe_json() for one host and return (result, urls requested)."""
    requested: list[str] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    async def go() -> ProbeResult:
        transport = httpx.MockTransport(recording_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sem = asyncio.Semaphore(1)
            prober = Prober(client, sem, check_json=True, respect_robots=False,
                             cache_dir=str(cache_dir))
            res = ProbeResult(ref_id="90101", name="Synthetic",
                              host="dash.example.test", family=family)
            await prober.probe_json(base, res)
            return res

    return asyncio.run(go()), requested


def _never_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request should have been made, got {request.url}")


def test_a_family_with_no_registered_endpoint_is_asked_for_nothing(tmp_path):
    # The sharp end of the change: 335 of 336 candidate requests in the
    # first live sample missed, and every family below has nothing but
    # misses on record. Nothing observed means nothing requested -- these
    # hosts now cost exactly the one root request the politeness contract
    # promises.
    empty = [f for f, paths in FAMILY_CANDIDATES.items() if not paths]
    assert empty, "expected at least one family with no registered endpoint"
    for family in empty:
        res, requested = _run_probe_json(_never_called, tmp_path, family)
        assert requested == [], family
        assert res.json_endpoint is None
    assert list(tmp_path.iterdir()) == []


def test_a_host_with_no_family_at_all_is_asked_for_nothing(tmp_path):
    # fingerprint() matched nothing, so there is no family to target and no
    # basis for guessing. looks_like_dashboard() may still have said yes --
    # under the old eight-path sweep that was enough to cost the sysop
    # eight requests.
    res, requested = _run_probe_json(_never_called, tmp_path, None)
    assert requested == []
    assert res.json_endpoint is None


def test_a_family_added_since_the_last_sweep_is_asked_for_nothing(tmp_path):
    # A signature added after the sample was taken has no observations
    # behind it yet, so it is absent from the map -- and absent must mean
    # silent, not "fall back to the old guesses".
    res, requested = _run_probe_json(_never_called, tmp_path, "family-added-later")
    assert requested == []
    assert res.json_endpoint is None


def test_the_targeted_family_is_asked_for_exactly_its_registered_path(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SYNTHETIC_FRAGMENT,
                              headers={"content-type": "text/html"})

    res, requested = _run_probe_json(handler, tmp_path, TARGETED_FAMILY)
    assert requested == [f"https://dash.example.test/{TARGETED_PATH}"]

    # The observed response for this path is an HTML fragment, not JSON, so
    # json_endpoint stays unset -- the cache label is the only record that
    # the endpoint answered at all.
    assert res.json_endpoint is None
    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = [p.name for p in out_dir.glob("json-*.gz")]
    assert cached == [f"json-{TARGETED_PATH}-200.gz"]
    assert read_cached_response(out_dir / cached[0]) == SYNTHETIC_FRAGMENT


def test_a_404_on_the_registered_path_is_cached_with_its_status_in_the_label(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"error":"not found"}')

    res, requested = _run_probe_json(handler, tmp_path, TARGETED_FAMILY)
    assert len(requested) == 1
    assert res.json_endpoint is None

    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = sorted(p.name for p in out_dir.glob("json-*.gz"))
    assert cached == [f"json-{TARGETED_PATH}-404.gz"]

    # The body alone is byte-identical to what a broken-but-present 200
    # endpoint might also return -- distinguishing them must not require
    # decompressing every file, which is exactly why the label carries it.
    assert read_cached_response(out_dir / cached[0]) == '{"error":"not found"}'


def test_a_json_response_on_a_registered_path_is_recorded_as_the_json_endpoint(tmp_path):
    # No dashboard in the first sample ever returned JSON. This path is
    # kept covered because the moment one does, it is the Phase 1 prize.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"lastheard": []}',
                              headers={"content-type": "application/json"})

    res, requested = _run_probe_json(handler, tmp_path, TARGETED_FAMILY)
    assert res.json_endpoint == f"https://dash.example.test/{TARGETED_PATH}"

    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = list(out_dir.glob("json-*.gz"))
    assert len(cached) == len(requested) == 1
    assert cached[0].name.endswith("-200.gz")
    assert read_cached_response(cached[0]) == '{"lastheard": []}'


def test_a_404_and_a_200_for_the_same_candidate_path_do_not_collide(tmp_path):
    # Simulates a dashboard endpoint that 404'd on one sweep and came back
    # on a later one: same ref_id, host, and candidate path, different
    # status. The label must keep them as two distinct entries rather than
    # the newer one silently overwriting the older.
    path = cache_response("90101", "dash.example.test", f"json-{TARGETED_PATH}-404",
                           '{"error":"not found"}', cache_dir=str(tmp_path))
    other = cache_response("90101", "dash.example.test", f"json-{TARGETED_PATH}-200",
                            '{"lastheard": []}', cache_dir=str(tmp_path))

    assert path != other
    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = sorted(p.name for p in out_dir.glob("json-*.gz"))
    assert len(cached) == 2
    assert read_cached_response(path) == '{"error":"not found"}'
    assert read_cached_response(other) == '{"lastheard": []}'
