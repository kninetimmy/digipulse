"""Tests for Prober.probe_json()'s caching of JSON-candidate responses --
specifically that the HTTP status of each candidate is recoverable offline
from the cache alone (PR #13 review, required fix 1). Before this fix, a
404 on a hypothesised endpoint and a 200 carrying a genuine JSON body wrote
byte-indistinguishable cache entries: an analyst globbing json-*.gz to
retune JSON_CANDIDATES could not tell them apart without re-fetching from
the sysop.

Uses httpx.MockTransport so no network access happens anywhere in this
file. This project's test suite has no async plugin configured, so each
async call is driven through asyncio.run() from an ordinary sync test.
"""

import asyncio

import httpx

from ysfprobe import JSON_CANDIDATES, ProbeResult, Prober, cache_key, cache_response, read_cached_response


def _run_probe_json(handler, cache_dir, base="https://dash.example.test/"):
    async def go() -> ProbeResult:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            sem = asyncio.Semaphore(1)
            prober = Prober(client, sem, check_json=True, respect_robots=False,
                             cache_dir=str(cache_dir))
            res = ProbeResult(ref_id="90101", name="Synthetic", host="dash.example.test")
            await prober.probe_json(base, res)
            return res

    return asyncio.run(go())


def test_a_404_on_every_candidate_is_cached_with_its_status_in_the_label(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"error":"not found"}')

    res = _run_probe_json(handler, tmp_path)
    assert res.json_endpoint is None

    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = sorted(p.name for p in out_dir.glob("json-*.gz"))
    assert len(cached) == len(JSON_CANDIDATES)
    assert all(name.endswith("-404.gz") for name in cached)

    # The body alone is byte-identical to what a broken-but-present 200
    # endpoint might also return -- distinguishing them must not require
    # decompressing every file, which is exactly why the label carries it.
    for path in out_dir.glob("json-*.gz"):
        assert read_cached_response(path) == '{"error":"not found"}'


def test_a_200_json_hit_stops_the_sweep_and_is_labelled_with_its_status(tmp_path):
    first_path = JSON_CANDIDATES[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/{first_path}":
            return httpx.Response(
                200, text='{"lastheard": []}',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, text='{"error":"not found"}')

    res = _run_probe_json(handler, tmp_path)
    assert res.json_endpoint == f"https://dash.example.test/{first_path}"

    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = list(out_dir.glob("json-*.gz"))
    # probe_json() returns the instant it finds a hit, so only the winning
    # candidate was ever requested (and cached).
    assert len(cached) == 1
    assert cached[0].name.endswith("-200.gz")
    assert read_cached_response(cached[0]) == '{"lastheard": []}'


def test_a_404_and_a_200_for_the_same_candidate_path_do_not_collide(tmp_path):
    # Simulates a dashboard endpoint that 404'd on one sweep and came back
    # on a later one: same ref_id, host, and candidate path, different
    # status. The label must keep them as two distinct entries rather than
    # the newer one silently overwriting the older.
    path = cache_response("90101", "dash.example.test", f"json-{JSON_CANDIDATES[0]}-404",
                           '{"error":"not found"}', cache_dir=str(tmp_path))
    other = cache_response("90101", "dash.example.test", f"json-{JSON_CANDIDATES[0]}-200",
                            '{"lastheard": []}', cache_dir=str(tmp_path))

    assert path != other
    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    cached = sorted(p.name for p in out_dir.glob("json-*.gz"))
    assert len(cached) == 2
    assert read_cached_response(path) == '{"error":"not found"}'
    assert read_cached_response(other) == '{"lastheard": []}'
