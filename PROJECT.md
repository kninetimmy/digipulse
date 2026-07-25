# YSF Activity Index — Project State

**Name:** `digipulse` (settled 2026-07-25; earlier working name was `ysfindex`)
**Status:** Phase 0 spike written, not yet run against the live network
**Repo:** <https://github.com/kninetimmy/digipulse> — public, Apache-2.0
**Last updated:** 2026-07-25

> Note: single-doc handoff, written to be read cold by a fresh session.
> Sections are self-contained if it later needs splitting or indexing.

---

## 1. The problem

There are roughly 1,700 registered YSF (Yaesu System Fusion) reflectors. The
official host list sorts them by **connected user count**, which measures idle
hotspots, not conversation. A reflector with 40 connected hotspots can be
completely silent; one with 3 nodes can be running a weekly net.

**There is no way to find out where anything is actually happening on the
Fusion network.** No aprs.fi, no BrandMeister Hoseline equivalent. Every
existing dashboard is a per-reflector PHP log-scraper that only benefits the
sysop of that one reflector.

This project builds the missing layer: a public index that ranks reflectors by
**observed voice activity**, detects recurring nets, and exposes it as an API
anyone's client can consume.

## 2. What this project is NOT

Decided deliberately, do not drift:

- **Not a DV client.** DroidStar (AD8DP, GPL, Qt) already connects to
  YSF/FCS/DMR/P25/NXDN/D-STAR, works with or without an AMBE dongle, and runs
  on Linux/Windows/macOS/Android/iOS. Do not build a sixth fork.
- **Not a vocoder project.** See §6.
- **Not a reflector dashboard.** Those exist and are crowded.

The index is a **service**, not an app. Its value is that DroidStar users,
Pi-Star/WPSD owners, and anyone else can consume it regardless of client.

## 3. Landscape (already researched — don't re-litigate)

| Thing | Status |
|---|---|
| **DroidStar** (`nostar/DroidStar`) | GPL Qt client. YSF/FCS DN+VW, DMR, P25, NXDN, D-STAR, AllStar. AMBE dongle optional. Multiple forks: 9M2PJU (vocoders compiled in, no dongle), bi7jta, DroidPiStar (GPIO/embedded), DudeShield. |
| **Per-reflector dashboards** | `dg9vh/YSFReflector-Dashboard` (PHP, unmaintained), `ShaYmez/YSFReflector-Dashboard2` (Tailwind, JS live updates → implies a JSON endpoint), `dg9vh/WSYSFDash` (websockets), `iu5jae/pYSFReflector3` (Python reflector + SQLite collector — richest data: QSOs w/ gateway, radio type, coordinates, FICH info). |
| **Protocol reference** | `g4klx/YSFClients` (GPL) — canonical YSF gateway/reflector. `JimZAH/ysf-reflector-monitor` — minimal "connect as client, print activity", good starting read. |
| **RF-side decode** | `hb9uf/gr-ysf` (GNU Radio, parses FICH, surfaces callsigns), `lwvmobile/dsd-fme` (C, YSF sync/FICH/DCH). Both usable as reference if the RF branch is ever revived. |

### ⚠ Registry migration — resolved 2026-07-25

The reflector registry **changed hands in 2025**. DG9VH handed YSFHosts.txt
maintenance onward effective 2025-06-01, and the old
`register.ysfreflector.de/export_csv.php` is no longer canonical.

The live registry is **RefCheck.Radio**, at <https://hostfiles.refcheck.radio>.
The landing page gates the links behind a terms checkbox; the files themselves
are at stable paths:

| Format | URL |
|---|---|
| Plain text | `https://hostfiles.refcheck.radio/YSFHosts.txt` |
| JSON | `https://hostfiles.refcheck.radio/YSFHosts.json` |

P25, NXDN and M17 host files follow the same pattern, which matters for the
deferred second-adapter work.

**Format verified against a real download, 2026-07-25.** The text export is
semicolon-delimited. RefCheck's landing page calls it "tab-delimited" — that
description is wrong; there is not a single tab in the file. 1,416 records,
uniformly 7 fields:

```
00006;GR-HELLAS Zone A;(YCS202);46.59.68.211;42000;000;
  ID ; Name          ; Descr  ; Address    ; Port; Users
```

`parse_hosts()` reads fields 0–4 and ignores the rest, so **it parses this
correctly as written.** Field 6 is a user count rather than the historic
`Comment`, but nothing reads it. No parser change is needed.

**The text export is still the wrong source, for a different reason.** Its
Address column is a bare IPv4 for **1,415 of 1,416** records. `candidate_urls()`
sees a bare IP and emits `http://<ip>/` only — no HTTPS attempt, and no Host
header the reflector's vhost would recognise. That probes default vhosts rather
than dashboards: ~1,400 requests spent on sysops to learn almost nothing.

**Use the JSON export.** It carries what the flat file discards:

| Field | Coverage |
|---|---|
| `url` — declared dashboard URL, scheme included (781 http / 406 https) | 83.8 % |
| `ipv4` | 99.9 % |
| `sponsor` | 82.5 % |
| `dns` — real hostname | 57.6 % |
| `ipv6` | 7.0 % |
| `country` | 100 % |

Plus `port`, `user_count`, `network_type`, `dns_cache_updated_at` and
`last_verified_at` per record, under a `reflectors` array alongside a
`_refcheck_metadata` block.

**This reshapes Phase 0.** The registry already declares a dashboard URL for
83.8 % of reflectors. The probe's question is no longer "guess where the
dashboard is" but "verify what the registry already says, and fingerprint what
answers." That is a better experiment and a considerably politer one — it also
means the ≥50 % gate in §4 should be read against reachable declared URLs, not
against blind scheme-guessing.

**Publisher terms — binding constraints, not suggestions:**

- **One request per hostfile per hour.** Cache to disk; never fetch per probe
  run. `--hosts-file` becomes the normal path, `--hosts-url` the exception.
- **A unique identifying User-Agent is required**; generic curl/wget defaults
  are blocked. The spike's callsign-bearing UA already satisfies this, and this
  is independent confirmation that §9's politeness stance is table stakes.
- Files are regenerated roughly every 30 minutes, so hourly is plenty fresh.
- Headers must remain unaltered and redistribution with modified attribution is
  prohibited — **do not commit the host file to the repo** (it is gitignored).
- **Commercial use is prohibited without explicit permission.** Fine for a free
  public index; revisit if that ever changes.

## 4. Current state — Phase 0 spike

**File:** `ysfprobe.py` (Python 3, single file, needs `httpx`)

Answers one question: *of the registered reflectors, how many expose a
dashboard we can parse, and what software is it running?*

**Verified (unit-tested against fixtures):**
- Host-file parsing incl. malformed lines and extra trailing fields
- Fingerprint precedence (forks match before the generic ancestor)
- Version extraction from the real dg9vh footer string
- Hostname → both schemes, bare IP → http only
- Report generation and the GO/PARTIAL/NO-GO verdict gate

**Known wrong (found 2026-07-25, fix not yet written):**
- The `--hosts-url` default points at `dvref.com`, which is not the registry.
  It is `https://hostfiles.refcheck.radio/YSFHosts.{txt,json}`.
- There is no JSON host-file reader, so the spike cannot use the declared `url`
  the registry supplies for 83.8 % of reflectors. `candidate_urls()` guesses
  schemes off a bare IP instead, which is both worse data and ruder. See §3.

**Confirmed correct after all:** `parse_hosts()`'s semicolon split matches the
real file exactly. An earlier note in this doc claimed the export was
tab-delimited and the parser therefore broken; that came from RefCheck's page
description, not from the file, and is wrong.

**Still unverified:**
- `JSON_CANDIDATES` paths are **hypotheses**, not observed endpoints
- Anonymisation regex is untuned against real dashboards
- No real HTML has ever passed through the fingerprinter

**Run order:**
```bash
pip install httpx
# 1. download the host file ONCE (one request per hour is the publisher's limit)
#    and eyeball the column layout before trusting it
# 2. fix parse_hosts() for the real delimiter, then small sample first
python ysfprobe.py --callsign <YOURCALL> --hosts-file YSFHosts.txt --limit 50
# 3. inspect unidentified titles, add signatures, re-run
# 4. full sweep, then
python ysfprobe.py --report
```

**Decision gate:**
- **≥50% parseable** → scraping is the primary source, build as designed
- **25–50%** → curated subset only; "network-wide" leaves the README
- **<25%** → scraping is dead; pivot to node-based observation + sysop opt-in

## 5. Phases

| # | Deliverable | Exit gate |
|---|---|---|
| 0 | `ysfprobe.py` fingerprint sweep | Parseable % measured; GO/PARTIAL/NO-GO called |
| 1 | Parser suite — one extractor per software family, all emitting the same normalised record | Last-heard pulled reliably from top-2 families for 7 consecutive days |
| 2 | Collector + adaptive scheduler (poll frequency tracks observed activity) | 14 days unattended, zero firewall blocks, parser health metrics green |
| 3 | Scoring engine | Correctly flags a net you already know exists, without being told |
| 4 | Public index — static JSON API + a page | Someone who is not you uses it |

Phases 1–2 are where this dies. Phase 3 is the fun part and it is third on purpose.

## 6. Vocoder / legal notes (context only — not in scope)

Recorded so it isn't re-researched:

- The gatekeeper is **DVSI**, not Yaesu. Yaesu owns Wires-X and the C4FM spec;
  DVSI owns AMBE+2 and claims patents, copyright, trademark and trade secret.
  DVSI's own site states that criminal copyright infringement "including
  infringement without monetary gain" is investigated by the FBI. **The
  non-commercial argument does not apply.**
- Community-tracked patent status (secondhand, not a patent search, not legal
  advice): D-Star-era AMBE patents expired ~2017. The remaining AMBE+2 patent
  (DMR/Fusion/NXDN) was filed 2003, granted late in 2013 → US expiry ~2028.
  Expected to have lapsed in EU/Canada in 2024; never patented in China,
  refused in Japan. `mbelib` has been public since 2010 with no DMCA takedowns.
- **This project needs none of it.** YSFD packet headers carry gateway and
  source callsigns as plaintext ASCII. Activity indexing is a metadata problem.
  Never add an audio pipeline to the collector.

## 7. Architecture decisions

### Decided

**Single Rust service.** `reqwest` + `scraper`. Accepts slower parser iteration
in exchange for single-binary deploy and reusing existing Rust experience.
*Reversal trigger:* if Phase 1 reveals >10 distinct HTML variants requiring
weekly churn, split parsers into a Python sidecar and eat the ops cost.

**SQLite behind a repository trait.** Estimated volume is low millions of rows
per year — comfortably SQLite territory. WAL mode, single writer. The
architectural move is the trait, not the engine: keep the swap to Postgres
cheap without paying for it now.

**Precomputed static JSON for serving.** The index is hourly-fresh for
everything except "on the air now." Generate rollups as static files; carve out
one small live endpoint. No query load, trivially cacheable, cheap forever.

**Split deployment.** Pi 5 runs the node daemon (needs to be near the radios).
A cheap VPS or Cloudflare Pages serves the index. Push, don't pull. Do not
expose the home Pi as a public service.

*Windows support for the node daemon is a stretch goal* — not required now, and
explicitly not worth delaying Phase 1 for. It is cheap if kept in mind and
expensive to retrofit, so avoid gratuitously Linux-only choices: no hardcoded
POSIX paths, no systemd-only service assumptions, nothing fork-based. Rust's
std and `tokio` are cross-platform by default, so mostly this is a discipline
about paths and process management rather than real work.

**Parser health as a first-class metric.** Scrapers fail *silently* — a
dashboard updates, the extractor returns zero rows, and a busy reflector gets
indexed as dead. Track per-family extraction success rate from day one and
alert on drops. This is the single highest-value piece of instrumentation in
the project.

**Licensing:** YSFClients and DroidStar are both **GPL**. Reading them for
protocol reference is fine; copying code makes this project GPL. Decide the
license before the first commit, and keep clean-room notes if going permissive.

### Open

- Data sources beyond scraping: own-node observation for ground truth on ~10
  reflectors (calibrates staleness/loss in scraped data), and possibly a
  sysop-installable push agent.
- FCS reflectors are a separate network with separate discovery — second
  adapter, deferred.
- The normalised record schema. **This is the next design task.** Every parser
  writes to this contract; getting it wrong is expensive to undo.

## 8. Scoring model (design notes for Phase 3)

Transmission count is a bad metric: one lonely rag-chewer looks busy, bridged
reflectors firehose DMR traffic that isn't really Fusion activity, and nets
spike hard enough to swamp the baseline.

Signals worth computing:

- **Distinct callsigns per window** — conversation, not chatter
- **Reciprocity** — ≥2 distinct calls within ~60s = a real QSO
- **Median inter-transmission gap** — tight gaps mean live exchange
- **Bridge detection** — flag reflectors dominated by gateway callsigns
- **7-day autocorrelation → recurring net windows.** *This is the killer
  feature.* "Tuesdays 2000 local, ~12 participants" is something nobody can
  currently tell you about any reflector.

Output buckets: `live_now` / `active_today` / `weekly_net` / `quiet` / `dead`.

## 9. Non-negotiable constraints

**Politeness.** Identifying User-Agent with callsign (`ysfprobe.py` refuses to
run without `--callsign` — keep that behaviour in the collector). Conditional
GETs, robots.txt respected, low concurrency, adaptive backoff. A sysop reading
their access log should shrug, not firewall you. This project can be killed
socially long before it's killed technically.

**Privacy.** Aggregate reflector activity is uncontroversial. A global
"where has this callsign been heard" search is surveillance-flavoured, and some
dashboards already anonymise callsigns deliberately. Ship aggregates publicly;
per-callsign lookup is opt-out at minimum, and worth considering opt-in.

**Never ask sysops to change anything.** Write parsers for what exists. The
moment the project requires cooperation to function, it stops functioning.

## 10. Eventual goals

1. A public, free, no-account API that answers "where is Fusion happening right
   now" and "when does this reflector's net run"
2. Adopted as a data source by an existing client (DroidStar host list sorted by
   real activity would be the win condition)
3. Historical archive — long-run activity trends across the Fusion network,
   which currently nobody has
4. *Optional, much later:* the always-on personal node — presence on the
   reflectors you care about, unified activity feed, PTT from a browser. Only
   after the index stands on its own.

## 11. Next actions

1. ~~Confirm the registry's host-file export URL and field layout~~ — **done
   2026-07-25**, see §3. It is RefCheck.Radio, the text export is tab-delimited,
   and a JSON export exists.
2. ~~Pick a name and a license; initial commit~~ — **done**: `digipulse`,
   Apache-2.0, <https://github.com/kninetimmy/digipulse>.
3. **Add a JSON host-file reader and probe the registry's declared `url`.**
   `parse_hosts()` needs no change; keep it for the text fallback. The win is
   retiring `candidate_urls()` guesswork wherever a `url` exists (83.8 %), and
   falling back to `dns` before `ipv4`.
4. `--limit 50` sample run; inspect unidentified titles; add signatures
5. Full sweep, call the gate
6. Design the normalised record schema (blocks all of Phase 1)
