# digipulse

A public index that ranks YSF (Yaesu System Fusion) reflectors by **observed
voice activity** rather than connected-user count, detects recurring nets, and
exposes it as an API.

The official host list sorts reflectors by connected users, which measures idle
hotspots rather than conversation. A reflector with 40 connected hotspots can be
completely silent; one with 3 nodes can be running a weekly net. There is
currently no way to find where anything is actually *happening* on the Fusion
network — no aprs.fi, no Hoseline equivalent. This builds that missing layer.

## Status: Phase 0 — feasibility, not yet run

This repository currently contains one thing: `ysfprobe.py`, a reconnaissance
spike that answers a single question — *of the ~1,700 registered reflectors, how
many expose a dashboard we can parse, and what software is it running?*

That number decides whether the approach is viable at all:

| Parseable | Verdict |
|---|---|
| ≥ 50 % | scraping is a viable primary data source |
| 25–50 % | curated subset only, not network-wide |
| < 25 % | scraping is dead; pivot to node-based collection |

Nothing has been run against the live network yet. See [`PROJECT.md`](PROJECT.md)
for the full design, the phase gates, and the reasoning behind each decision.

## Usage

```bash
pip install -r requirements.txt

# --callsign is mandatory; the probe refuses to run without identifying you
python ysfprobe.py --callsign <YOURCALL> --hosts-file YSFHosts.txt --limit 50
python ysfprobe.py --report
```

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The test suite runs entirely against synthetic fixtures — it never touches
the network and never reads a real RefCheck.Radio export.

## Conduct

This project reads public dashboards and asks nothing of reflector sysops.

- One root request per host, an identifying User-Agent carrying the operator's
  callsign, robots.txt honoured, low concurrency, adaptive backoff. A sysop
  reading their access log should shrug, not firewall you.
- Aggregate reflector activity is what gets published. A global "where has this
  callsign been heard" lookup is surveillance-flavoured and is not a goal.
- No audio is ever touched. YSF headers carry callsigns as plaintext ASCII, so
  this is a metadata problem — there is no vocoder here and there never will be.

## License

[Apache-2.0](LICENSE). YSFClients and DroidStar (both GPL) are referenced for
protocol understanding only; no code is copied from them.
