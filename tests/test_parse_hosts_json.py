"""Tests for parse_hosts_json() -- RefCheck.Radio's JSON export."""

import pytest

from fixtures import SYNTHETIC_JSON_EXPORT
from ysfprobe import parse_hosts_json


def test_parses_all_valid_records():
    reflectors, _ = parse_hosts_json(SYNTHETIC_JSON_EXPORT)
    assert [r.ref_id for r in reflectors] == ["90101", "90102", "90103"]


def test_declared_url_is_preserved_and_blank_url_normalises_to_none():
    reflectors, _ = parse_hosts_json(SYNTHETIC_JSON_EXPORT)
    by_id = {r.ref_id: r for r in reflectors}
    assert by_id["90101"].url == "https://dash.example.test/status"
    assert by_id["90102"].url is None  # empty string in the export -> None


def test_dns_preferred_over_ipv4_as_host_and_ip_only_has_no_dns():
    reflectors, _ = parse_hosts_json(SYNTHETIC_JSON_EXPORT)
    by_id = {r.ref_id: r for r in reflectors}
    assert by_id["90101"].host == "dash.example.test"
    assert by_id["90103"].host == "203.0.113.13"  # no dns, falls back to ipv4
    assert by_id["90103"].dns is None


def test_non_dict_and_id_or_host_missing_records_are_collected_as_unparsed():
    # A bare string element and a record with neither designator nor a host
    # both belong in the unparsed list, not silently dropped.
    _, unparsed = parse_hosts_json(SYNTHETIC_JSON_EXPORT)
    assert len(unparsed) == 2


def test_missing_reflectors_array_raises():
    with pytest.raises(ValueError):
        parse_hosts_json('{"_refcheck_metadata": {}}')
