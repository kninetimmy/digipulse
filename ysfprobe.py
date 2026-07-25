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
    python ysfprobe.py --callsign KO4XXX --hosts-url https://... 
    python ysfprobe.py --callsign KO4XXX --hosts-file YSFHosts.txt --limit 100
    python ysfprobe.py --report
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

try:
    import httpx
except ImportError:
    sys.exit("need httpx: pip install httpx")

DB_PATH = "ysfprobe.db"
VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Host file parsing
# ---------------------------------------------------------------------------

# YSFHosts.txt is semicolon-delimited, historically:
#   ID;Name;Description;Address;Port;Comment
# Field count has drifted between registry generations, so parse defensively
# and record anything we could not interpret rather than dropping it silently.


@dataclass
class Reflector:
    ref_id: str
    name: str
    description: str
    host: str
    port: Optional[int]
    raw: str


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
            )
        )
    return reflectors, unparsed


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------

# Ordered: first match wins, so put specific forks above the generic ancestor.


@dataclass
class Signature:
    family: str
    patterns: list[re.Pattern]
    version_re: Optional[re.Pattern] = None


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
    Signature(
        "ycs",
        [re.compile(r"\bYCS\d*\b"),
         re.compile(r"xreflector", re.I)],
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
# Common anonymisation renderings seen in GDPR-conscious dashboards.
ANON_RE = re.compile(r"(\*{2,}|X{3,}\d|\bANON\b|\bhidden\b)", re.I)


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


def candidate_urls(host: str) -> list[str]:
    """A hostname might have TLS; a bare IP almost certainly will not."""
    try:
        ipaddress.ip_address(host)
        return [f"http://{host}/"]
    except ValueError:
        return [f"https://{host}/", f"http://{host}/"]


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


class Prober:
    def __init__(self, client: httpx.AsyncClient, sem: asyncio.Semaphore,
                 check_json: bool, respect_robots: bool):
        self.client = client
        self.sem = sem
        self.check_json = check_json
        self.respect_robots = respect_robots

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
            if r.status_code != 200:
                continue
            ctype = r.headers.get("content-type", "")
            body = r.text[:200_000]
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

        async with self.sem:
            start = time.perf_counter()
            last_err: Optional[str] = None

            for url in candidate_urls(ref.host):
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
                m = TITLE_RE.search(body)
                res.title = (m.group(1).strip()[:200] if m else None)
                res.family, res.dash_version = fingerprint(body)
                res.callsigns_visible = len(set(CALLSIGN_RE.findall(body.upper())))
                res.anonymised = bool(ANON_RE.search(body))

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

    reachable = scalar("SELECT COUNT(*) c FROM probe WHERE status BETWEEN 200 AND 399")
    known = scalar("SELECT COUNT(*) c FROM probe WHERE family IS NOT NULL")
    with_json = scalar("SELECT COUNT(*) c FROM probe WHERE json_endpoint IS NOT NULL")
    anon = scalar("SELECT COUNT(*) c FROM probe WHERE anonymised=1")
    robots = scalar("SELECT COUNT(*) c FROM probe WHERE robots_blocked=1")

    def pct(n: int) -> str:
        return f"{n:5d}  ({100 * n / total:5.1f}%)"

    print(f"\n  reflectors probed        {total:5d}")
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

    # The decision gate.
    parseable = known / total
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
    if args.hosts_file:
        text = open(args.hosts_file, encoding="utf-8", errors="replace").read()
    else:
        async with httpx.AsyncClient(follow_redirects=True) as c:
            text = (await c.get(args.hosts_url, timeout=30.0)).text

    reflectors, unparsed = parse_hosts(text)
    if unparsed:
        print(f"warn: {len(unparsed)} host-file lines unparsed "
              f"(format may have changed under DVRef)", file=sys.stderr)
        for line in unparsed[:3]:
            print(f"      {line[:100]}", file=sys.stderr)

    if args.limit:
        reflectors = reflectors[: args.limit]
    print(f"probing {len(reflectors)} reflectors, concurrency {args.concurrency}")

    ua = (f"ysfprobe/{VERSION} (+amateur radio reflector directory research; "
          f"operator {args.callsign}; one request per host)")
    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency * 2)

    async with httpx.AsyncClient(
        headers={"User-Agent": ua}, follow_redirects=True,
        limits=limits, verify=False,
    ) as client:
        prober = Prober(client, sem, not args.no_json_probe, not args.ignore_robots)
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
    p.add_argument("--hosts-url", default="https://dvref.com/ysf/hosts",
                   help="host file URL -- VERIFY THIS against DVRef before trusting it")
    p.add_argument("--hosts-file", help="local YSFHosts.txt instead of fetching")
    p.add_argument("--limit", type=int, help="probe only the first N (start at 50)")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--db", default=DB_PATH)
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
