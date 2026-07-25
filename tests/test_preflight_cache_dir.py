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
    # hosts_file deliberately points at a path that does not exist. If
    # preflight_cache_dir() were called anywhere other than first in run(),
    # this would instead fail with FileNotFoundError from open() on the
    # hosts file -- proving the ordering, not just that *some* error occurs.
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
    with pytest.raises(OSError):
        asyncio.run(run(args))
