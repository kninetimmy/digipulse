"""Tests for preflight_cache_dir() -- the fail-closed check that proves
cache_dir is actually writable before a single sysop is contacted (PR #13
review, required fix 2). Without this, a cache write failure discovered
mid-sweep from cache_response() -- which raises straight out of
Prober.probe() with no guard in run() -- aborted the whole sweep and
discarded every result already collected for hosts already probed.

No network access anywhere in this file.
"""

import argparse
import asyncio
import re

import pytest

from ysfprobe import preflight_cache_dir, run


def test_creates_the_cache_directory_when_missing(tmp_path):
    target = tmp_path / "does" / "not" / "exist"
    assert not target.exists()
    preflight_cache_dir(str(target))
    assert target.is_dir()


def test_leaves_no_leftover_files_behind_on_success(tmp_path):
    preflight_cache_dir(str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_is_safe_to_call_more_than_once(tmp_path):
    preflight_cache_dir(str(tmp_path))
    preflight_cache_dir(str(tmp_path))  # must not raise the second time
    assert list(tmp_path.iterdir()) == []


def test_raises_when_the_cache_dir_path_is_actually_a_file(tmp_path):
    # Reproduces the FileExistsError the reviewer found: a same-named file
    # sitting where the cache directory needs to go. Must fail closed, not
    # silently succeed or get swallowed.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    with pytest.raises(OSError):
        preflight_cache_dir(str(blocked))


def test_run_fails_before_reading_the_hosts_file_when_cache_dir_is_unusable(tmp_path):
    # hosts_file deliberately points at a path that does not exist. The
    # assertion is narrowed to FileExistsError -- the exact error
    # preflight_cache_dir() raises for a blocked cache_dir -- rather than the
    # broader OSError, because FileNotFoundError (what open() on the missing
    # hosts file would raise) is itself an OSError subclass: an OSError
    # assertion here would pass under either ordering and prove nothing. With
    # this narrower type, if preflight_cache_dir() were called anywhere other
    # than first in run(), the hosts file open() would fail first and this
    # test would fail on the exception type.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    args = argparse.Namespace(
        callsign="TEST1AAA",
        hosts_file=str(tmp_path / "does-not-exist.json"),
        hosts_url="https://hostfiles.example.invalid/YSFHosts.json",
        limit=None,
        concurrency=1,
        db=str(tmp_path / "out.db"),
        cache_dir=str(blocked),
        no_json_probe=True,
        ignore_robots=True,
    )
    with pytest.raises(FileExistsError, match=re.escape(blocked.name)):
        asyncio.run(run(args))


def test_run_fails_on_blocked_cache_dir_even_with_a_perfectly_valid_hosts_file(tmp_path):
    # Same blocked cache_dir, but hosts_file this time is valid and parses to
    # zero reflectors -- so if preflight_cache_dir() were not called first,
    # run() would sail straight through hosts parsing (nothing to probe, no
    # network access) and reach store()/report() without error. Isolates the
    # preflight as the cause of failure, independent of what state the hosts
    # file is in.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    hosts_file = tmp_path / "empty.json"
    hosts_file.write_text('{"reflectors": []}', encoding="utf-8")
    args = argparse.Namespace(
        callsign="TEST1AAA",
        hosts_file=str(hosts_file),
        hosts_url="https://hostfiles.example.invalid/YSFHosts.json",
        limit=None,
        concurrency=1,
        db=str(tmp_path / "out.db"),
        cache_dir=str(blocked),
        no_json_probe=True,
        ignore_robots=True,
    )
    with pytest.raises(FileExistsError, match=re.escape(blocked.name)):
        asyncio.run(run(args))
