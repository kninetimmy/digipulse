"""Tests for parse_registry() -- dispatch on content, not on filename."""

from fixtures import SYNTHETIC_JSON_EXPORT, SYNTHETIC_TEXT_EXPORT
from ysfprobe import parse_registry


def test_json_content_dispatches_to_json_parser_with_no_filename_hint():
    reflectors, _ = parse_registry(SYNTHETIC_JSON_EXPORT)
    assert [r.ref_id for r in reflectors] == ["90101", "90102", "90103"]


def test_json_content_dispatches_to_json_parser_even_with_a_misleading_hint():
    # The URL a hostfile is fetched from need not end in .json -- dispatch
    # must key off the leading '{', not the filename.
    reflectors, _ = parse_registry(SYNTHETIC_JSON_EXPORT, source_hint="export.txt")
    assert [r.ref_id for r in reflectors] == ["90101", "90102", "90103"]


def test_leading_whitespace_before_the_brace_still_dispatches_to_json():
    padded = "\n   \t" + SYNTHETIC_JSON_EXPORT
    reflectors, _ = parse_registry(padded)
    assert [r.ref_id for r in reflectors] == ["90101", "90102", "90103"]


def test_semicolon_content_dispatches_to_text_parser():
    reflectors, _ = parse_registry(SYNTHETIC_TEXT_EXPORT)
    assert [r.ref_id for r in reflectors] == ["90001", "90002"]
