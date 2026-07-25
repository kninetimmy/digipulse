# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A public index that ranks YSF (Yaesu System Fusion) reflectors by **observed voice
activity** rather than connected-user count, detects recurring nets, and exposes it
as an API. Read `PROJECT.md` first — it is the authoritative design doc, written to
be read cold, and it carries the landscape research, phase gates, and the reasoning
behind every decision below. Do not re-litigate what §3 and §7 already settled.

**Current state:** Phase 0. One file, `ysfprobe.py`, a reconnaissance spike that has
never been run against the live network. Its only job is to measure what percentage
of the ~1,700 registered reflectors expose a parseable dashboard, which decides
whether the whole scraping strategy is viable (`report()` prints the GO / PARTIAL /
NO-GO gate at ≥50% / 25–50% / <25%).

## Commands

```bash
pip install httpx                     # only dependency; installed (0.28.1)

# Probe (--callsign is mandatory and refuses to run without it, by design)
python ysfprobe.py --callsign <YOURCALL> --hosts-file YSFHosts.txt --limit 50
python ysfprobe.py --callsign <YOURCALL> --hosts-url <verified-dvref-url>
python ysfprobe.py --report           # re-print the gate from the existing ysfprobe.db
```

Always `--limit 50` first, inspect the unidentified titles, add signatures, then
sweep. Results accumulate in `ysfprobe.db` (SQLite, `INSERT OR REPLACE` keyed on
`(ref_id, host)`), so re-running is idempotent per host.

**No test framework is set up.** `PROJECT.md` §4 refers to unit tests against
fixtures — those were written during design and never landed in this repo. There is
no test runner and no CI. Ask before picking either.

Licensed **Apache-2.0** (chosen 2026-07-25). The codebase is clean-room with respect
to the GPL projects in §3 — keep it that way; see the contamination note below.

## ysfprobe.py structure

Linear pipeline, each stage independently testable:

`parse_hosts()` → `Prober.probe()` → `fingerprint()` → `store()` → `report()`

Things that will bite you if changed carelessly:

- **`SIGNATURES` order is load-bearing.** First match wins, so forks must sit above
  the generic ancestor they derive from (`ysfdash2-shaymez` before `ysfdash-dg9vh`).
  Appending a new signature to the end silently changes nothing; insert by specificity.
- **One root request per host** is the politeness contract, not an optimisation.
  The `JSON_CANDIDATES` sweep only fires when `looks_like_dashboard()` already
  returned true, and sleeps 0.3s between candidates. Keep that gate.
- **robots.txt fails open** (absent/unreadable/oversized → allowed). Deliberate: a
  missing robots.txt is not a prohibition. An actual `Disallow` aborts the host.
- **`verify=False`** on the client is intentional — reflector dashboards are hobbyist
  boxes with expired and self-signed certs, and we read public HTML. Don't "fix" it.
- `parse_hosts()` collects unparsed lines instead of dropping them, and `run()`
  prints a warning. That warning is the early-detection system for a registry format
  change; do not silence it.

## Unverified assumptions in the spike

Flagged because a silent wrong guess poisons everything downstream:

- The `--hosts-url` default (`https://dvref.com/ysf/hosts`) is **a guess.** The
  registry moved from DG9VH to DVRef on 2025-06-01; confirm the real export URL and
  whether the field layout is still `ID;Name;Description;Address;Port;Comment` by
  hand before trusting any output.
- `JSON_CANDIDATES` paths are hypotheses, not observed endpoints.
- `ANON_RE` is untuned; no real dashboard HTML has ever passed through the
  fingerprinter.

## Where this is going (decided — see PROJECT.md §7)

- **Phase 1+ is a single Rust service** (`reqwest` + `scraper`), not Python. The
  spike is Python because it is a spike. Reversal trigger: >10 distinct HTML variants
  needing weekly churn → split parsers into a Python sidecar.
- **SQLite behind a repository trait.** The trait is the architectural move; the
  engine is not. WAL, single writer.
- **Precomputed static JSON** for serving, with one small live "on the air now"
  endpoint carved out. No query load.
- **Split deployment:** Pi 5 runs the node daemon near the radios and pushes; a VPS
  or Cloudflare Pages serves the index. The home Pi is never publicly exposed.
- **Parser health is a first-class metric from day one.** Scrapers fail silently —
  a busy reflector indexed as dead is the characteristic failure of this project.
  Track per-family extraction success rate and alert on drops.

The next design task is **the normalised record schema** — every parser writes to
that contract and it is expensive to undo. It blocks all of Phase 1.

## Non-negotiable constraints

- **Politeness over throughput.** Identifying User-Agent carrying the operator's
  callsign, conditional GETs, low concurrency, adaptive backoff. This project can be
  killed socially long before it is killed technically.
- **Never require sysops to change anything.** Write parsers for what exists. The
  moment it needs cooperation to function, it stops functioning.
- **Privacy:** ship aggregates publicly. A global "where has this callsign been
  heard" lookup is surveillance-flavoured — opt-out at minimum.
- **Never add an audio pipeline.** This is a metadata problem; YSFD headers carry
  callsigns as plaintext ASCII. Vocoder territory (DVSI/AMBE+2) is out of scope
  permanently — §6 records the legal reasoning so it isn't re-researched.
- **GPL contamination:** YSFClients and DroidStar are GPL. Reading them for protocol
  reference is fine; copying code makes this project GPL. Keep clean-room notes if
  going permissive.
- **Scope discipline:** this is not a DV client (DroidStar exists), not a vocoder
  project, not another per-reflector dashboard.

## Naming

The project is **`digipulse`** — settled 2026-07-25 and used for the GitHub repo.
`PROJECT.md` still carries the earlier working name `ysfindex` in its header and
lists "pick a name and a license" as an open action in §11; both are now decided,
so treat the doc's header as stale rather than authoritative on this one point.

## Session memory

memhub is initialized here (`.memhub/project.sqlite`, gitignored). `PROJECT.md` is
ingested as 15 searchable chunks, retrieval is hybrid + reranker. Prefer `memhub
recall` over re-reading `PROJECT.md` mid-session, and `memhub locate` once there is
enough code to index. `/wrap-up` at session end routes updates back into the DB.
