# LAN Watch

**A polite, passive presence monitor for your own home network.**

LAN Watch learns every device that comes and goes on your LAN — phones,
laptops, TVs, printers, that one smart plug you forgot about — without
ever logging into any of them or pulling data off them. It watches what
the network itself reveals, keeps a tidy registry, and writes a simple
event log you can read at a glance: who joined, who left, and what each
device announces about itself.

One Python file. Standard library only. No dependencies, no accounts,
no cloud — your network's story stays on your machine.

By **Dimon Global Group**.

## What it does

Each pass (one sweep of your network) does three things:

1. **Presence sweep** — an ICMP ping sweep of your local /24 subnet
   records which addresses answer. New addresses produce a `JOIN`
   event; an address missing from two consecutive sweeps produces a
   `LEAVE`.
2. **Passive listening** — for a listening window (90 seconds by
   default), LAN Watch joins the mDNS and SSDP multicast groups and
   records the announcements devices broadcast about themselves:
   service names (`._tcp` / `._udp`), `.local` hostnames, and SSDP
   headers (`Server`, `ST`, `USN`, `Location`, `NT`). This part is
   purely passive — it only listens.
3. **First-sight port note** — the first time a device is registered,
   LAN Watch makes a bare TCP connect attempt against a short list of
   common ports (22, 53, 80, 443, 445, 3389, 8000, 8080) and notes
   which ones accept a connection. No login is attempted and no data
   is exchanged — it is the network equivalent of noticing a door
   exists, not opening it.

Results accumulate in a **device registry** (`devices.json`) and an
**event log** (`events.jsonl`), so over days and weeks you build an
honest picture of what lives on your network.

## How it works

- The sweep is deliberately gentle: a 12-worker thread pool pings the
  subnet in waves rather than spawning a process storm.
- A device is only marked gone after **two consecutive missed sweeps**,
  so a sleeping phone doesn't flap in and out of the log.
- Announcements are deduplicated per device — you get an `ANNOUNCE`
  event the first time a device says something new, not every time it
  repeats itself.
- The watcher is built to be left running: in daemon mode a failed
  pass is logged and the watcher carries on.

## Requirements

- Python 3 (standard library only — nothing to install)
- A `ping` command on your `PATH` (present on Linux, macOS, and Termux)
- Permission to bind UDP ports 5353 and 1900 for the listeners; if a
  listener can't start, LAN Watch logs that and continues with the
  sweep

## Usage

One pass, then exit:

```
python3 lan_watch.py --once
```

Run as a watcher (a pass every 5 minutes by default):

```
python3 lan_watch.py --daemon
```

Useful options:

```
--listen SECONDS     passive listening window per pass (default 90)
--interval SECONDS   daemon interval between passes (default 300)
--records-dir PATH   where the records live
```

The records directory can also be set with an environment variable:

```
LAN_WATCH_HOME=~/lan-records python3 lan_watch.py --daemon
```

Default records location: `./lan-watch-records` in the current
directory. A starter records directory with an empty registry is
included in this repository.

## The records

| File | Contents |
| --- | --- |
| `devices.json` | The registry, keyed by IP address: `first_seen`, `last_seen`, the first-sight `ports` list, announced `services` and `announcements`, and presence bookkeeping. |
| `events.jsonl` | One JSON object per line: `{"ts", "kind", "ip", "detail"}` where `kind` is `JOIN`, `LEAVE`, or `ANNOUNCE`. |
| `watch.log` | Timestamped pass summaries from daemon runs. |

## Privacy & fair use

LAN Watch is a tool for understanding **your own** network. Run it
only on networks you own or are explicitly authorized to monitor.
Everything it learns stays in local files under your control — it
sends nothing anywhere. It never attempts a login, never exploits
anything, and never reads data from the devices it observes; the
registry is built from pings, a first-sight connect check, and
broadcasts the devices themselves chose to announce.

## License

MIT — see [LICENSE](LICENSE).

---

*LAN Watch is part of the Dimon Global Group public release program:
working tools, published openly once the in-house line has moved past
them.*
