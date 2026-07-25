"""Tests for _safe_slug()'s length handling -- specifically that an
over-long value loses its middle, never its tail.

The tail is load-bearing. cache_response() is handed a candidate label
shaped "json-<path>-<status>", so a tail truncation ate the "-404" that
tells a miss from a hit; worse, the 404 and the 200 for the same path then
sanitised to the SAME filename and the later write silently overwrote the
earlier, destroying the only offline record that the endpoint answered at
all. With the 64-character budget cache_response() uses, a candidate path
of 56 characters is already enough to trigger it.

No network access anywhere in this file; every write goes under pytest's
tmp_path, never the real CACHE_DIR.
"""

import re

from ysfprobe import _safe_slug, cache_key, cache_response, read_cached_response

_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def test_a_value_within_the_budget_is_left_alone():
    assert _safe_slug("json-lh.php-404", max_len=64) == "json-lh.php-404"


def test_an_over_long_value_is_cut_to_the_budget():
    assert len(_safe_slug("x" * 500, max_len=64)) == 64


def test_an_over_long_value_keeps_both_ends():
    slug = _safe_slug("HEAD" + "-" * 200 + "TAIL", max_len=64)
    assert slug.startswith("HEAD")
    assert slug.endswith("TAIL")


def test_the_elided_result_is_still_a_single_safe_path_component():
    slug = _safe_slug("../../../etc/" + "a" * 200 + "/passwd", max_len=48)
    assert _SAFE_PATH_COMPONENT.match(slug), slug
    assert ".." not in slug


def test_the_windows_reserved_name_guard_still_fires():
    # The guard runs on whatever survives the length handling; moving that
    # handling must not have stepped past it.
    assert _safe_slug("CON") == "_CON"
    assert _safe_slug("NUL.gz") == "_NUL.gz"


def test_a_value_that_sanitises_to_nothing_still_yields_a_slug():
    # Everything here is outside the allowlist, so there is nothing left to
    # elide by the time the length handling runs.
    assert _safe_slug("///") == "x"


# ---------------------------------------------------------------------------
# The reason any of the above matters: cache labels
# ---------------------------------------------------------------------------

# 56 characters is the shortest candidate path that overflows
# cache_response()'s 64-character label budget: len("json-") + 56 +
# len("-404") == 65.
_OVERLONG_PATH = "a" * 56


def test_a_label_long_enough_to_truncate_still_distinguishes_404_from_200(tmp_path):
    miss = cache_response("90101", "dash.example.test",
                          f"json-{_OVERLONG_PATH}-404", "not found",
                          cache_dir=str(tmp_path))
    hit = cache_response("90101", "dash.example.test",
                         f"json-{_OVERLONG_PATH}-200", "<div>fragment</div>",
                         cache_dir=str(tmp_path))

    # Two files, not one silently overwriting the other...
    assert miss != hit
    out_dir = tmp_path / cache_key("90101", "dash.example.test")
    assert len(list(out_dir.glob("json-*.gz"))) == 2

    # ...and the status is still readable from the name alone, without
    # decompressing anything.
    assert miss.name.endswith("-404.gz")
    assert hit.name.endswith("-200.gz")

    assert read_cached_response(miss) == "not found"
    assert read_cached_response(hit) == "<div>fragment</div>"


def test_an_extravagantly_long_label_still_keeps_its_status_suffix(tmp_path):
    # Nothing about the fix depends on being only slightly over budget.
    path = cache_response("90101", "dash.example.test",
                          "json-" + "b" * 400 + "-503", "gateway down",
                          cache_dir=str(tmp_path))
    assert path.name.endswith("-503.gz")
    assert read_cached_response(path) == "gateway down"
