# Changelog

All notable changes to LAN Watch are documented here.

## [1.0.0] — 2026-11-01

First public edition.

- Passive LAN presence monitor in a single standard-library-only
  Python file: ICMP ping sweep of the local /24, passive mDNS and
  SSDP announcement listening, and a one-time common-port note when a
  device is first registered.
- Device registry (`devices.json`) plus a `JOIN` / `LEAVE` /
  `ANNOUNCE` event log (`events.jsonl`) and daemon summaries
  (`watch.log`).
- One-shot (`--once`) and daemon (`--daemon`) modes, with tunable
  listening window (`--listen`) and sweep interval (`--interval`).
- Records directory is now configurable — `--records-dir` flag or the
  `LAN_WATCH_HOME` environment variable, defaulting to
  `./lan-watch-records` — and the package ships with an empty starter
  registry.
- Gentle by design: 12-worker throttled sweep, and a device is only
  marked gone after two consecutive missed sweeps.
