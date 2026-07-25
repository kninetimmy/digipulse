"""Tests for cache_response() / read_cached_response() -- the write/read
round-trip that lets SIGNATURES, ANON_RE and FAMILY_CANDIDATES be tuned
offline against previously-fetched bodies instead of re-contacting sysops.

Every body below is invented for the test; none of it is real dashboard
HTML. Everything writes under pytest's tmp_path, never the real
CACHE_DIR -- no network access anywhere in this file.
"""

import os

from ysfprobe import cache_key, cache_response, read_cached_response

SYNTHETIC_BODY = (
    "<html><head><title>Synthetic Test Reflector</title></head>"
    "<body>YSFReflector-Dashboard V 2.0 last heard: W1AW</body></html>"
)


def test_write_then_read_round_trips_the_body_exactly(tmp_path):
    path = cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY,
                           cache_dir=str(tmp_path))
    assert read_cached_response(path) == SYNTHETIC_BODY


def test_round_trip_preserves_non_ascii_content(tmp_path):
    body = "<title>R\u00e9flecteur synthetique \u2014 caract\u00e8res \u00e9tendus</title>"
    path = cache_response("90101", "host.example.test", "root", body, cache_dir=str(tmp_path))
    assert read_cached_response(path) == body


def test_written_file_is_actually_gzip_compressed(tmp_path):
    path = cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY,
                           cache_dir=str(tmp_path))
    raw = path.read_bytes()
    assert raw[:2] == b"\x1f\x8b"  # gzip magic number
    assert raw != SYNTHETIC_BODY.encode("utf-8")  # actually compressed, not just renamed


def test_entry_lands_under_the_directory_named_by_cache_key(tmp_path):
    path = cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY,
                           cache_dir=str(tmp_path))
    expected_dir = tmp_path / cache_key("90101", "dash.example.test")
    assert path.parent == expected_dir


def test_root_and_json_candidate_bodies_for_the_same_host_share_a_directory(tmp_path):
    root_path = cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY,
                                cache_dir=str(tmp_path))
    json_path = cache_response("90101", "dash.example.test", "json-api.php",
                                '{"lastheard": []}', cache_dir=str(tmp_path))
    assert root_path.parent == json_path.parent
    assert root_path != json_path
    assert read_cached_response(root_path) == SYNTHETIC_BODY
    assert read_cached_response(json_path) == '{"lastheard": []}'


def test_different_hosts_land_in_different_directories(tmp_path):
    one = cache_response("90101", "dash-one.example.test", "root", SYNTHETIC_BODY,
                          cache_dir=str(tmp_path))
    two = cache_response("90101", "dash-two.example.test", "root", SYNTHETIC_BODY,
                          cache_dir=str(tmp_path))
    assert one.parent != two.parent


def test_re_probing_the_same_host_overwrites_the_previous_entry(tmp_path):
    # Matches store()'s INSERT OR REPLACE semantics keyed on (ref_id, host):
    # the cache is not an append-only log, the latest fetch wins.
    path_first = cache_response("90101", "dash.example.test", "root", "first body",
                                 cache_dir=str(tmp_path))
    path_second = cache_response("90101", "dash.example.test", "root", "second body",
                                  cache_dir=str(tmp_path))
    assert path_first == path_second
    assert read_cached_response(path_second) == "second body"


def test_no_temp_file_is_left_behind_after_a_normal_write(tmp_path):
    cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY, cache_dir=str(tmp_path))
    leftovers = [p for p in tmp_path.rglob("*") if ".tmp" in p.name]
    assert leftovers == []


def test_untrusted_ref_id_and_host_cannot_escape_the_cache_directory(tmp_path):
    # ref_id/host come straight from a third-party registry. Path
    # separators, '..', a drive letter, and a reserved Windows device name
    # must all be neutralised rather than crash the write or land outside
    # the cache directory.
    cache_dir = tmp_path / "cache"
    for ref_id, host in [
        ("../../../etc/passwd", "normal-host.example.test"),
        ("90101", "..\\..\\Windows\\System32"),
        ("C:\\Windows\\System32", "CON"),
        ("NUL", "COM1"),
    ]:
        path = cache_response(ref_id, host, "root", SYNTHETIC_BODY, cache_dir=str(cache_dir))
        resolved = path.resolve()
        base = cache_dir.resolve()
        # os.path.commonpath (not startswith) so a sibling like "cacheEVIL"
        # can never be mistaken for containment inside "cache". Portable
        # back to Python 3.8 -- Path.is_relative_to() is 3.9+.
        assert os.path.commonpath([str(resolved), str(base)]) == str(base)
        assert read_cached_response(path) == SYNTHETIC_BODY


def test_read_cached_response_accepts_a_plain_string_path(tmp_path):
    path = cache_response("90101", "dash.example.test", "root", SYNTHETIC_BODY,
                           cache_dir=str(tmp_path))
    assert read_cached_response(str(path)) == SYNTHETIC_BODY
