"""Tests for parse_hosts() -- the semicolon-delimited text export."""

from fixtures import SYNTHETIC_TEXT_EXPORT, SYNTHETIC_TEXT_UNPARSED_LINE
from ysfprobe import parse_hosts


def test_parses_well_formed_semicolon_records():
    reflectors, _ = parse_hosts(SYNTHETIC_TEXT_EXPORT)
    assert [r.ref_id for r in reflectors] == ["90001", "90002"]


def test_splits_all_seven_fields_including_trailing_separator():
    reflectors, _ = parse_hosts(SYNTHETIC_TEXT_EXPORT)
    first = reflectors[0]
    assert first.name == "Synthetic Net One"
    assert first.description == "Weekly practice net"
    assert first.host == "relay-one.example.test"
    assert first.port == 42001


def test_hostname_address_yields_dns_but_bare_ipv4_does_not():
    reflectors, _ = parse_hosts(SYNTHETIC_TEXT_EXPORT)
    by_id = {r.ref_id: r for r in reflectors}
    assert by_id["90001"].dns == "relay-one.example.test"
    assert by_id["90002"].dns is None  # bare IPv4 is not a usable hostname


def test_blank_and_comment_lines_are_silently_skipped():
    reflectors, unparsed = parse_hosts(SYNTHETIC_TEXT_EXPORT)
    # 2 real records, 1 malformed line -- the blank line and the comment
    # line contribute to neither list.
    assert len(reflectors) == 2
    assert len(unparsed) == 1


def test_collects_unparsed_lines_instead_of_dropping_them():
    # This is the early-warning system for a registry format change: a line
    # that doesn't split into enough fields must be visible, not silently
    # discarded.
    _, unparsed = parse_hosts(SYNTHETIC_TEXT_EXPORT)
    assert unparsed == [SYNTHETIC_TEXT_UNPARSED_LINE]
