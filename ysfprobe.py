#!/usr/bin/env python3
"""
ysfprobe -- Phase 0 reconnaissance for a YSF activity index.

Answers exactly one question: of the reflectors in the host file, how many
expose a dashboard we can parse, and what software family is it?

Everything else (scoring, API, node daemon) is downstream of that number.
If it comes back low, the project needs a different data strategy and we
want to know that after one evening, not after three weekends.

Deliberately conservative: one root request per host, an identifying
User-Agent, robots.txt honoured, low concurrency. A sysop reading their
access log should see a single polite hit and shrug.

Usage:
    pip install httpx

    # Download once -- RefCheck.Radio allows one request per hostfile per hour
    python ysfprobe.py --callsign KO4XXX --hosts-file YSFHosts.json --limit 50
    python ysfprobe.py --report

Prefer the JSON export. It declares a dashboard URL for most reflectors, so we
verify what the registry already says rather than guessing at an IP address.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import ipaddress
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import httpx
except ImportError:
    sys.exit("need httpx: pip install httpx")

DB_PATH = "ysfprobe.db"
CACHE_DIR = "ysfprobe_cache"
VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Host file parsing
# ---------------------------------------------------------------------------

# The registry is RefCheck.Radio. It publishes two exports:
#
#   YSFHosts.txt   semicolon-delimited, 7 fields:
#                    ID;Name;Description;Address;Port;UserCount;
#                  Field 6 was historically Comment; nothing here reads it.
#                  Address is a bare IPv4 for all but one record, which makes
#                  this export nearly useless for finding dashboards.
#
#   YSFHosts.json  {"_refcheck_metadata": {...}, "reflectors": [...]}
#                  Carries a declared dashboard `url` for ~84% of reflectors
#                  and a real hostname in `dns` for ~58%. Prefer this.
#
# Both parsers collect anything they could not interpret rather than dropping
# it silently -- that list is the early-warning system for a format change.


@dataclass
class Reflector:
    ref_id: str
    name: str
    description: str
    host: str
    port: Optional[int]
    raw: str
    # Declared dashboard URL, when the registry supplies one. Probing this
    # beats guessing a scheme, and costs the sysop exactly one request.
    url: Optional[str] = None
    # Hostname, when we have one. None means we only ever saw a bare IP, and
    # a bare IP cannot carry a Host header the reflector's vhost recognises.
    dns: Optional[str] = None


def _hostname_or_none(addr: str) -> Optional[str]:
    """A bare IP is not a usable hostname. Anything else, we treat as one."""
    try:
        ipaddress.ip_address(addr)
        return None
    except ValueError:
        return addr or None


def parse_hosts(text: str) -> tuple[list[Reflector], list[str]]:
    reflectors: list[Reflector] = []
    unparsed: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 5:
            unparsed.append(line)
            continue
        try:
            port = int(parts[4])
        except (ValueError, IndexError):
            port = None
        reflectors.append(
            Reflector(
                ref_id=parts[0],
                name=parts[1],
                description=parts[2],
                host=parts[3],
                port=port,
                raw=line,
                dns=_hostname_or_none(parts[3]),
            )
        )
    return reflectors, unparsed


def parse_hosts_json(text: str) -> tuple[list[Reflector], list[str]]:
    """RefCheck.Radio's JSON export.

    Preferred over the flat file: it declares a dashboard URL for most
    reflectors, so the probe verifies what the registry already says instead
    of guessing schemes against an IP address.
    """
    doc = json.loads(text)
    records = doc.get("reflectors")
    if records is None:
        raise ValueError(
            "registry JSON has no 'reflectors' array -- layout changed, "
            "re-inspect before trusting anything downstream"
        )

    reflectors: list[Reflector] = []
    unparsed: list[str] = []
    for rec in records:
        if not isinstance(rec, dict):
            unparsed.append(repr(rec)[:200])
            continue
        ref_id = str(rec.get("designator") or "").strip()
        dns = (rec.get("dns") or "").strip() or None
        ipv4 = (rec.get("ipv4") or "").strip() or None
        host = dns or ipv4
        if not ref_id or not host:
            unparsed.append(json.dumps(rec)[:200])
            continue
        port = rec.get("port")
        reflectors.append(
            Reflector(
                ref_id=ref_id,
                name=(rec.get("name") or "").strip(),
                description=(rec.get("description") or "").strip(),
                host=host,
                port=port if isinstance(port, int) else None,
                raw=json.dumps(rec, separators=(",", ":")),
                url=(rec.get("url") or "").strip() or None,
                dns=dns,
            )
        )
    return reflectors, unparsed


def parse_registry(text: str, source_hint: str = "") -> tuple[list[Reflector], list[str]]:
    """Dispatch on content, not on filename -- the URL may not end in .json."""
    if text.lstrip()[:1] == "{" or source_hint.endswith(".json"):
        return parse_hosts_json(text)
    return parse_hosts(text)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

# Ordered: first match wins, so put specific forks above the generic ancestor.


@dataclass
class Signature:
    family: str
    patterns: list[re.Pattern]
    version_re: Optional[re.Pattern] = None


# --- ycs vs. plain xlxd: what the first live sample got wrong ------------
#
# The first live sample fingerprinted 23 hosts as "ycs", every XLXnnn/XLXQRZ/
# XLXPOL-titled dashboard among them included, via two patterns ORed
# together: a literal `YCS` token, and `xreflector`. Two XLX-titled hosts
# (XLX070, XLX314) came back unidentified despite sharing that exact title
# shape with the rest -- an inconsistency, since a title shape is a property
# of the software that rendered it, not of the individual sysop.
#
# Reading the cached bodies (ysfprobe_cache/) resolved it: `xreflector` was
# never a YCS marker. It was matching a `<meta name="keywords">` tag that
# ships in the *xlxd* dashboard's own template -- xlxd's multi-protocol
# reflector branding has long used "XReflector" as a synonym for the
# project name itself, unrelated to the separate YCS server software. Every
# XLX-titled host that matched "ycs" did so through that meta tag alone,
# and the two that came back unidentified (XLX070, XLX314) simply had a
# sysop-customised `keywords` tag that no longer contained the word --
# confirmed by diffing that one tag's content across several XLX-titled
# hosts: identical stock wording on the hosts that matched, a wholly
# different custom string on the two that didn't. Nothing about the actual
# dashboard differed. The same accident also over-matched two "Fusion
# Dashboard"-titled hosts as ycs while two more, template-for-template
# identical (same script/stylesheet bundle, verified structurally), came
# back unidentified for the same reason.
#
# Genuine YCS dashboards, by contrast, carry their own software name as a
# literal token completely independent of that meta tag: in a page title
# ("YCS Dashboard"), in on-page links/buttons to the install's own numbered
# instance (e.g. a "YCSnnn" button), or in the hostname of a sibling page the
# dashboard itself links to (a "ycsNNN.<domain>" address). That token is
# case-inconsistent across real installs -- upper in on-page button text,
# lower in URLs -- so the pattern below adds re.I; the original was
# case-sensitive and silently missed the lower-case form. `xreflector` is
# dropped outright: it never identified YCS, only xlxd's unrelated branding.
#
# xlxd's own dashboards are identified instead by their title, which is the
# one thing consistently observed across every XLX-titled host regardless
# of which visual template a sysop has installed (the sample alone showed
# at least three distinct script/stylesheet bundles under this one title
# convention) -- either the bare designator ("XLXnnn") or the designator
# followed by "Reflector Dashboard". No non-XLX-titled host in the sample
# begins its title that way, so the pattern is anchored to the <title> tag
# rather than searched for as a bare substring.
SIGNATURES: list[Signature] = [
    Signature(
        "ysfdash2-shaymez",
        [re.compile(r"YSFReflector-Dashboard2", re.I),
         re.compile(r"dashboard2", re.I)],
    ),
    Signature(
        "wsysfdash",
        [re.compile(r"WSYSFDash", re.I)],
    ),
    Signature(
        "pysfreflector3",
        [re.compile(r"pYSFReflector", re.I),
         re.compile(r"\bpYSF3?\b")],
    ),
    # These four are each identified by one literal, software-specific title
    # string with no observed overlap against any other family in the
    # sample -- but "ycs" used to over-match on an unrelated meta tag (see
    # the block comment above) and swallowed one of them (Fusion Dashboard)
    # before this fix. Kept above "ycs"/"xlxd" on purpose: if either of
    # those two ever grows a broader pattern again, these narrower,
    # single-purpose ones must still get first look.
    Signature(
        "hub-monitor",
        [re.compile(r"HUB Monitor", re.I)],
    ),
    Signature(
        "fusion-dashboard",
        [re.compile(r"Fusion Dashboard", re.I)],
    ),
    Signature(
        "cumbriacq-backup",
        [re.compile(r"CumbriaCQ Backup Server", re.I)],
    ),
    Signature(
        "marras",
        [re.compile(r"MARRAS C4FM Multi Streams Reflector", re.I)],
    ),
    Signature(
        "ycs",
        [re.compile(r"\bYCS\d*\b", re.I)],
    ),
    Signature(
        "xlxd",
        [re.compile(r"<title[^>]*>\s*XLX[0-9A-Z]", re.I)],
    ),
    Signature(
        "ysfdash-dg9vh",
        [re.compile(r"YSFReflector-Dashboard", re.I),
         re.compile(r"dg9vh", re.I)],
        version_re=re.compile(r"YSFReflector-Dashboard\s+V\s*([0-9A-Za-z\-\.]+)", re.I),
    ),
    Signature(
        "mmdvm-generic",
        [re.compile(r"MMDVM", re.I), re.compile(r"Pi-Star|WPSD", re.I)],
    ),
]

# Endpoints worth a second look ONLY if the root already looked like a dashboard.
JSON_CANDIDATES = [
    "api.php", "json.php", "data.php", "status.json",
    "lh.php", "ajax.php", "api/status", "api/lastheard",
]

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
# Loose callsign shape: 1-2 alnum, digit, 1-4 letters. Deliberately permissive.
CALLSIGN_RE = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z]{1,4}\b")

# A callsign-shaped prefix immediately before a run of asterisks, e.g. the
# "AB1" in "AB1***". Same shape as CALLSIGN_RE's prefix (1-2 letters, a
# digit, then a few more letters/digits) but does NOT require the trailing
# run of letters CALLSIGN_RE does -- the asterisks are what stand in for
# those, so the token as a whole never looks like a complete callsign.
_ANON_PREFIX = r"\b[A-Z]{1,2}[0-9][A-Z0-9]{0,4}"

# What ANON_RE is defined to mean: this dashboard is displaying a
# redacted stand-in for a callsign -- NOT "this page's markup happens to
# contain the substring hidden or **". The first live sample (43 reachable
# dashboards, 28 flagged by the old pattern) showed the old pattern was
# measuring the latter: 26 of those 28 were \bhidden\b matching ordinary
# Bootstrap markup (an <input type="hidden">, a class="d-none hidden")
# present on nearly every dashboard; the other 2 were genuine redaction.
# \*{2,} matching the /** that opens a CSS or JSDoc comment block is a
# real forward-looking risk over the full ~1,700-host registry -- it just
# didn't happen to occur in this particular 43-host sample (zero "/**" or
# "**/" in any of the 43 bodies). Either way, none of it has anything to
# do with a redacted callsign, and the flagged cohort actually had MORE
# visible callsigns than the unflagged one -- the flag was measuring the
# opposite of what it claimed to.
#
# Checked cell-by-cell against the 43 real dashboard bodies in
# ysfprobe_cache/ (only 2 of the 43 hosts show any genuine redaction, but
# between them there are 126 individually redacted "lastheard" cells),
# genuine redaction takes one of these shapes:
#   - a callsign-shaped prefix immediately followed by 2+ asterisks, e.g.
#     "AB1***" -- the dashboard shows the first few characters and masks
#     the rest;
#   - a bare run of 3+ asterisks with nothing callsign-shaped in front of
#     it, that isn't itself the delimiter of a CSS/JS comment -- either
#     the whole callsign masked rather than just a suffix, or (half the
#     redacted cells on one of the two redacting hosts) a callsign whose
#     leading zero is rendered as the HTML entity &Oslash; (the ham
#     zero-slash convention) rather than a literal digit: probe() reads
#     r.text, so that entity never decodes, and a prefix regex anchored on
#     [0-9] can never see the digit. This branch does not require a
#     callsign-shaped prefix at all, specifically so it still catches
#     that case -- e.g. "N&Oslash;U***" is caught here, not above, because
#     there is no ASCII digit for the prefix branch to anchor on. (An
#     earlier version of this pattern required 4+ bare asterisks, which
#     missed 18 of these 126 cells -- 11 of them on the host where
#     zero-slash calls make up 10 of 20 redacted cells.)
#   - a run of 3+ literal X's followed by a digit, e.g. "XXXXX1" -- the
#     same idea rendered with X instead of an asterisk;
#   - the literal placeholder word ANON.
# The bare-run branch excludes matches immediately preceded OR followed by
# '/' or '*': that's what keeps out both the "/**" that opens a CSS/JSDoc
# comment and the "**/" (or a decorative "/*** ... ***/" banner) that
# closes one, without having to special-case comment syntax. The
# prefix+asterisks branch additionally excludes a match immediately
# followed by a digit -- otherwise "**" is also the JS/Python
# exponentiation operator, and a variable name shaped like a callsign
# (e.g. "x2**3") would false-positive; zero occurrences of that in the
# 43-host sample, but it's a live risk over the full ~1,700-host registry.
ANON_RE = re.compile(
    rf"({_ANON_PREFIX}\*{{2,}}(?!\d)|(?<![/*])\*{{3,}}(?![/*])|X{{3,}}\d|\bANON\b)",
    re.I,
)


@dataclass
class ProbeResult:
    ref_id: str
    name: str
    host: str
    url: Optional[str] = None
    final_url: Optional[str] = None
    status: Optional[int] = None
    scheme_worked: Optional[str] = None
    server_header: Optional[str] = None
    family: Optional[str] = None
    dash_version: Optional[str] = None
    title: Optional[str] = None
    json_endpoint: Optional[str] = None
    callsigns_visible: int = 0
    anonymised: bool = False
    robots_blocked: bool = False
    elapsed_ms: Optional[int] = None
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def fingerprint(body: str) -> tuple[Optional[str], Optional[str]]:
    for sig in SIGNATURES:
        if any(p.search(body) for p in sig.patterns):
            version = None
            if sig.version_re:
                m = sig.version_re.search(body)
                if m:
                    version = m.group(1)
            return sig.family, version
    return None, None


def looks_like_dashboard(body: str, family: Optional[str], title: Optional[str]) -> bool:
    if family:
        return True
    hay = f"{title or ''} {body[:4000]}".lower()
    return any(k in hay for k in ("last heard", "lastheard", "reflector", "gateway", "callsign"))


def candidate_urls(ref: Reflector) -> list[str]:
    """Declared URL first, then the registry hostname, then nothing.

    A bare IP is deliberately never probed. Without a Host header the
    reflector's vhost recognises, it answers with a default site -- so the
    request costs a sysop something and tells us nothing. An empty list means
    "unmeasurable", which report() counts apart from "failed".
    """
    if ref.url:
        return [ref.url]
    if ref.dns:
        return [f"https://{ref.dns}/", f"http://{ref.dns}/"]
    return []


# ---------------------------------------------------------------------------
# Raw response cache
# ---------------------------------------------------------------------------

# store() only ever persists DERIVED fields (family, title, callsigns_visible,
# ...) computed by regexes that, before the first real sweep, have never seen
# a live dashboard. If SIGNATURES, ANON_RE, or JSON_CANDIDATES turn out to be
# wrong, finding that out must not mean re-probing the same sysops -- "one
# root request per host" makes that expensive to redo. So every body this
# project reads gets written here too, gzipped, the moment it's read: raw
# HTML in, tuning happens entirely offline afterwards.

_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")
# Windows reserves these names (with or without an extension) in every
# directory. The Pi target doesn't care, but this project is developed on
# Windows too, and a registry record calling itself "con" or "nul" must not
# produce an unwritable path.
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _safe_slug(value: str, max_len: int = 48) -> str:
    """Best-effort human-readable filesystem fragment.

    Never trusted alone for safety or uniqueness -- every caller pairs this
    with a hash of the raw value (see cache_key()). ref_id and host come from
    a third-party registry and are untrusted: dropping everything outside a
    conservative ASCII allowlist removes path separators (both '/' and
    '\\'), '..', and drive letters (':' is not in the allowlist) in one
    step, before the reserved-name check runs on what's left.
    """
    ascii_value = value.encode("ascii", "ignore").decode("ascii")
    slug = _SAFE_SLUG_RE.sub("_", ascii_value).strip("._")
    slug = slug[:max_len] or "x"
    # Windows treats NAME.anything as reserved too, not just the bare name --
    # check the part before the first dot, the same way Windows does.
    if slug.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        slug = f"_{slug}"
    return slug


def cache_key(ref_id: str, host: str) -> str:
    """Deterministic, filesystem-safe key for one (ref_id, host) pair.

    The hash suffix is what actually guarantees safety and uniqueness: it's
    a digest of the untrusted raw values, each prefixed by its length so
    ("a", "bc") and ("ab", "c") can never hash to the same string. The
    sanitised prefix carries no safety weight -- it only lets a human skim
    the cache directory without opening every file.
    """
    digest = hashlib.sha256(
        f"{len(ref_id)}:{ref_id}:{host}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{_safe_slug(ref_id)}__{_safe_slug(host)}__{digest}"


def cache_response(ref_id: str, host: str, label: str, body: str,
                    cache_dir: str = CACHE_DIR) -> Path:
    """Persist one response body gzipped, keyed on (ref_id, host).

    Called the instant a body is read rather than buffered -- unlike
    store(), which only writes once at the end of a whole sweep, an
    interrupted run must keep every entry already fetched. `label`
    distinguishes the root dashboard body ("root") from each JSON_CANDIDATES
    path tried against the same host, so one reflector's whole footprint
    lands in a single directory. Writes via a temp file + atomic rename so a
    hard kill mid-write can never leave a truncated .gz that looks like a
    complete entry.

    The pid-only temp-file suffix is only collision-free because this
    function is a plain, non-async def: nothing here ever awaits, so two
    calls from different coroutines in the same event loop can never
    interleave inside it, and one process only ever has one pid. If this is
    ever moved onto a thread (e.g. via asyncio.to_thread()), the pid suffix
    stops being unique on its own and needs thread/task identity folded in
    too.
    """
    out_dir = Path(cache_dir) / cache_key(ref_id, host)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{_safe_slug(label, max_len=64)}.gz"
    data = gzip.compress(body.encode("utf-8", "replace"))
    tmp = target.with_name(target.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target


def preflight_cache_dir(cache_dir: str) -> None:
    """Create cache_dir and prove it is actually writable, once, before a
    single sysop is contacted.

    cache_response() raises straight out of Prober.probe() on any I/O
    error, and run() does `results.append(await coro)` with no guard around
    it -- so if a cache write failed partway through a sweep, the exception
    would abort the whole thing before store() or report() ever run,
    discarding every result already collected for hosts already contacted.
    Exercising the exact same mkdir + temp-file + atomic-rename sequence
    here, before the AsyncClient used for probing is even opened, turns an
    unwritable or otherwise unusable cache_dir (no permission, a plain file
    sitting where a directory needs to go, a full disk, ...) into a
    fail-closed error at startup instead of a mid-sweep data loss.
    """
    out_dir = Path(cache_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    probe = out_dir / f".preflight{os.getpid()}"
    tmp = probe.with_name(probe.name + ".tmp")
    tmp.write_bytes(b"")
    os.replace(tmp, probe)
    probe.unlink()


def read_cached_response(path) -> str:
    """Inverse of cache_response(): decompress and decode a cached body."""
    return gzip.decompress(Path(path).read_bytes()).decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


class Prober:
    def __init__(self, client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 check_json: bool, respect_robots: bool, cache_dir: str = CACHE_DIR):
        self.client = client
        self.sem = sem
        self.check_json = check_json
        self.respect_robots = respect_robots
        self.cache_dir = cache_dir

    async def robots_allows(self, base: str) -> bool:
        if not self.respect_robots:
            return True
        try:
            r = await self.client.get(urljoin(base, "/robots.txt"), timeout=6.0)
            if r.status_code != 200 or len(r.text) > 100_000:
                return True
            rp = RobotFileParser()
            rp.parse(r.text.splitlines())
            return rp.can_fetch("*", base)
        except Exception:
            return True  # absent or unreadable robots.txt is not a prohibition

    async def probe_json(self, base: str, res: ProbeResult) -> None:
        for path in JSON_CANDIDATES:
            url = urljoin(base, path)
            try:
                r = await self.client.get(url, timeout=8.0)
            except Exception:
                continue
            # Cache whatever came back regardless of status -- a 404 on a
            # hypothesised endpoint is itself useful offline evidence that
            # the path doesn't exist for this dashboard family. The status
            # is folded into the label (not just the body) so that fact
            # survives a glob of the cache directory: two cached bodies that
            # are both e.g. {"error":"not found"} must stay distinguishable
            # from a genuine 200 without decompressing anything.
            body = r.text[:200_000]
            cache_response(res.ref_id, res.host, f"json-{path}-{r.status_code}",
                            body, self.cache_dir)
            if r.status_code != 200:
                continue
            ctype = r.headers.get("content-type", "")
            if "json" in ctype.lower():
                res.json_endpoint = url
                return
            stripped = body.lstrip()
            if stripped[:1] in ("{", "["):
                try:
                    json.loads(body)
                    res.json_endpoint = url
                    res.notes.append("json-without-content-type")
                    return
                except Exception:
                    pass
            await asyncio.sleep(0.3)  # do not machine-gun a single host

    async def probe(self, ref: Reflector) -> ProbeResult:
        res = ProbeResult(ref_id=ref.ref_id, name=ref.name, host=ref.host)
        if not ref.host:
            res.error = "no-host"
            return res

        urls = candidate_urls(ref)
        if not urls:
            # Registry gave us only a bare IP. Not a failure -- unmeasurable,
            # and counted separately so it never drags the gate down.
            res.error = "no-usable-address"
            return res

        async with self.sem:
            start = time.perf_counter()
            last_err: Optional[str] = None

            for url in urls:
                res.url = url
                if not await self.robots_allows(url):
                    res.robots_blocked = True
                    res.error = "robots-disallow"
                    return res
                try:
                    r = await self.client.get(url, timeout=10.0)
                except Exception as exc:
                    last_err = f"{type(exc).__name__}"
                    continue

                res.status = r.status_code
                res.final_url = str(r.url)
                res.scheme_worked = urlparse(url).scheme
                res.server_header = r.headers.get("server")
                res.elapsed_ms = int((time.perf_counter() - start) * 1000)

                if r.status_code >= 400:
                    last_err = f"http-{r.status_code}"
                    continue

                body = r.text[:400_000]
                cache_response(res.ref_id, res.host, "root", body, self.cache_dir)
                m = TITLE_RE.search(body)
                res.title = (m.group(1).strip()[:200] if m else None)
                res.family, res.dash_version = fingerprint(body)
                res.callsigns_visible = len(set(CALLSIGN_RE.findall(body.upper())))
                res.anonymised = bool(ANON_RE.search(body))
                # Which source got us here matters for parser health later: a
                # declared URL that stops working is a registry problem, a dns
                # guess that stops working is ours.
                res.notes.append("declared-url" if ref.url else "dns-fallback")

                if self.check_json and looks_like_dashboard(body, res.family, res.title):
                    await self.probe_json(str(r.url), res)
                return res

            res.error = last_err or "unreachable"
            return res


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS probe (
    ref_id TEXT, name TEXT, host TEXT, url TEXT, final_url TEXT,
    status INTEGER, scheme_worked TEXT, server_header TEXT,
    family TEXT, dash_version TEXT, title TEXT, json_endpoint TEXT,
    callsigns_visible INTEGER, anonymised INTEGER, robots_blocked INTEGER,
    elapsed_ms INTEGER, error TEXT, notes TEXT,
    probed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ref_id, host)
);
CREATE INDEX IF NOT EXISTS idx_family ON probe(family);
"""


def store(results: Iterable[ProbeResult], db_path: str = DB_PATH) -> None:
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.executemany(
        """INSERT OR REPLACE INTO probe
           (ref_id,name,host,url,final_url,status,scheme_worked,server_header,
            family,dash_version,title,json_endpoint,callsigns_visible,
            anonymised,robots_blocked,elapsed_ms,error,notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (r.ref_id, r.name, r.host, r.url, r.final_url, r.status,
             r.scheme_worked, r.server_header, r.family, r.dash_version,
             r.title, r.json_endpoint, r.callsigns_visible,
             int(r.anonymised), int(r.robots_blocked), r.elapsed_ms,
             r.error, ",".join(r.notes) or None)
            for r in results
        ],
    )
    con.commit()
    con.close()


def report(db_path: str = DB_PATH) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) c FROM probe").fetchone()["c"]
    if not total:
        print("no rows -- run a probe first")
        return

    def scalar(sql: str) -> int:
        return con.execute(sql).fetchone()["c"]

    # Records the registry described only by a bare IP were never contacted.
    # They are unmeasured, not dead, so they must not dilute the gate.
    skipped = scalar("SELECT COUNT(*) c FROM probe WHERE error='no-usable-address'")
    probed = total - skipped
    if not probed:
        print(f"\n  {total} records, none probeable -- every one was IP-only.")
        print("  Use the JSON export: https://hostfiles.refcheck.radio/YSFHosts.json\n")
        con.close()
        return

    reachable = scalar("SELECT COUNT(*) c FROM probe WHERE status BETWEEN 200 AND 399")
    known = scalar("SELECT COUNT(*) c FROM probe WHERE family IS NOT NULL")
    with_json = scalar("SELECT COUNT(*) c FROM probe WHERE json_endpoint IS NOT NULL")
    anon = scalar("SELECT COUNT(*) c FROM probe WHERE anonymised=1")
    robots = scalar("SELECT COUNT(*) c FROM probe WHERE robots_blocked=1")
    declared = scalar("SELECT COUNT(*) c FROM probe WHERE notes LIKE '%declared-url%'")

    def pct(n: int) -> str:
        return f"{n:5d}  ({100 * n / probed:5.1f}%)"

    print(f"\n  reflectors in registry   {total:5d}")
    print(f"  no usable address        {skipped:5d}   (IP only -- not probed, not counted)")
    print(f"  probed                   {probed:5d}")
    print(f"    via declared url       {declared:5d}")
    print(f"  http reachable           {pct(reachable)}")
    print(f"  fingerprinted family     {pct(known)}")
    print(f"  machine-readable JSON    {pct(with_json)}")
    print(f"  appears anonymised       {pct(anon)}")
    print(f"  robots.txt disallowed    {pct(robots)}")

    print("\n  software families")
    for row in con.execute(
        "SELECT COALESCE(family,'(unidentified)') f, COUNT(*) c "
        "FROM probe GROUP BY f ORDER BY c DESC"
    ):
        print(f"    {row['f']:<24} {row['c']:5d}")

    print("\n  top failure modes")
    for row in con.execute(
        "SELECT error e, COUNT(*) c FROM probe WHERE error IS NOT NULL "
        "GROUP BY e ORDER BY c DESC LIMIT 8"
    ):
        print(f"    {row['e']:<24} {row['c']:5d}")

    # The decision gate, measured against what we actually contacted.
    parseable = known / probed
    print("\n  " + "-" * 46)
    if parseable >= 0.50:
        verdict = "GO -- scraping is a viable primary source"
    elif parseable >= 0.25:
        verdict = "PARTIAL -- viable for a curated subset, not network-wide"
    else:
        verdict = "NO-GO -- need node-based or sysop-opt-in collection instead"
    print(f"  {parseable:.0%} parseable  =>  {verdict}")
    print("  " + "-" * 46 + "\n")
    con.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> None:
    # Fail closed, before contacting anyone: an unwritable or unusable
    # cache_dir must abort here, not partway through a sweep after some
    # sysops have already been contacted (see preflight_cache_dir()).
    preflight_cache_dir(args.cache_dir)

    ua = (f"ysfprobe/{VERSION} (+amateur radio reflector directory research; "
          f"operator {args.callsign}; one request per host)")

    if args.hosts_file:
        text = open(args.hosts_file, encoding="utf-8", errors="replace").read()
        source = args.hosts_file
    else:
        # RefCheck.Radio blocks generic clients outright and allows one request
        # per hostfile per hour, so identify ourselves and cache what we get.
        async with httpx.AsyncClient(
            follow_redirects=True, headers={"User-Agent": ua}
        ) as c:
            text = (await c.get(args.hosts_url, timeout=30.0)).text
        source = args.hosts_url

    reflectors, unparsed = parse_registry(text, source)
    if unparsed:
        print(f"warn: {len(unparsed)} registry records unparsed "
              f"(export format may have changed)", file=sys.stderr)
        for line in unparsed[:3]:
            print(f"      {line[:100]}", file=sys.stderr)

    if args.limit:
        reflectors = reflectors[: args.limit]

    with_url = sum(1 for r in reflectors if r.url)
    with_dns = sum(1 for r in reflectors if not r.url and r.dns)
    unreachable = len(reflectors) - with_url - with_dns
    print(f"{len(reflectors)} reflectors: {with_url} declared url, "
          f"{with_dns} hostname only, {unreachable} IP-only (skipped)")
    print(f"probing {with_url + with_dns}, concurrency {args.concurrency}")

    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency * 2)

    async with httpx.AsyncClient(
        headers={"User-Agent": ua}, follow_redirects=True,
        limits=limits, verify=False,
    ) as client:
        prober = Prober(
            client, sem, not args.no_json_probe, not args.ignore_robots, args.cache_dir,
        )
        results: list[ProbeResult] = []
        tasks = [prober.probe(r) for r in reflectors]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            results.append(await coro)
            if i % 25 == 0:
                print(f"  {i}/{len(reflectors)}", file=sys.stderr)

    store(results, args.db)
    report(args.db)


def main() -> None:
    p = argparse.ArgumentParser(description="Phase 0 YSF dashboard fingerprinter")
    p.add_argument("--callsign", help="your callsign, sent in User-Agent (required to probe)")
    p.add_argument("--hosts-url",
                   default="https://hostfiles.refcheck.radio/YSFHosts.json",
                   help="registry export URL. RefCheck.Radio allows one request "
                        "per hostfile per hour -- prefer --hosts-file")
    p.add_argument("--hosts-file", help="local YSFHosts.txt instead of fetching")
    p.add_argument("--limit", type=int, help="probe only the first N (start at 50)")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--cache-dir", default=CACHE_DIR,
                   help="gzipped raw response bodies, keyed on (ref_id, host), "
                        "for offline fingerprinter tuning. Holds third-party "
                        "dashboard HTML that must not be redistributed -- the "
                        "default path is gitignored, a custom one here is not")
    p.add_argument("--no-json-probe", action="store_true")
    p.add_argument("--ignore-robots", action="store_true")
    p.add_argument("--report", action="store_true", help="print report from existing db")
    args = p.parse_args()

    if args.report:
        report(args.db)
        return
    if not args.callsign:
        sys.exit("--callsign is required: identify yourself to the sysops you are probing")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
