"""Tests for cache_key() -- deterministic, filesystem-safe keys derived from
(ref_id, host) pairs read from a third-party, untrusted registry.

No filesystem or network access here; see test_cache_response.py for the
write/read round-trip against a real (temporary) directory.
"""

import re

from ysfprobe import cache_key

# A single path component: no separators, no '..', nothing outside a
# conservative ASCII allowlist -- safe to join onto a base directory on
# both Windows and Linux without further checking.
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def test_same_inputs_always_produce_the_same_key():
    assert cache_key("90101", "dash.example.test") == cache_key("90101", "dash.example.test")


def test_different_ref_id_produces_a_different_key():
    assert cache_key("90101", "dash.example.test") != cache_key("90102", "dash.example.test")


def test_different_host_produces_a_different_key():
    assert cache_key("90101", "dash.example.test") != cache_key("90101", "other.example.test")


def test_key_is_a_single_filesystem_safe_path_component():
    key = cache_key("weird ref/id\\has spaces", "weird host:*?<>|")
    assert _SAFE_PATH_COMPONENT.match(key), key


def test_path_traversal_sequences_do_not_survive_into_the_key():
    # A registry record made entirely of '..' and separators must not
    # produce a key that, joined onto a cache directory, escapes it.
    key = cache_key("../../../etc/passwd", "..\\..\\Windows\\System32")
    assert "/" not in key
    assert "\\" not in key
    assert ".." not in key


def test_drive_letter_is_neutralised():
    key = cache_key("C:\\Windows\\System32", "host")
    assert ":" not in key
    assert _SAFE_PATH_COMPONENT.match(key), key


def test_non_ascii_is_stripped_without_raising():
    key = cache_key("r\u00e9flecteur-\u260e", "\u262d.example.test")
    assert _SAFE_PATH_COMPONENT.match(key), key


def test_two_non_ascii_only_inputs_still_produce_distinct_keys():
    # Both sanitise down to an empty human-readable prefix -- only the hash
    # suffix can keep them apart, so it must actually do so.
    assert cache_key("\u260e\u260e", "host") != cache_key("\u262d\u262d", "host")


def test_length_prefixed_hash_disambiguates_concatenation_collisions():
    # Hashing "ref_id" and "host" naively concatenated would make ("a", "bc")
    # collide with ("ab", "c"). The length prefix must prevent that.
    assert cache_key("a", "bc") != cache_key("ab", "c")


def test_empty_ref_id_or_host_does_not_raise_and_yields_a_key():
    key = cache_key("", "")
    assert _SAFE_PATH_COMPONENT.match(key), key
