#!/usr/bin/env python3
"""lan_watch.py — a polite, passive presence monitor for your own LAN.

LAN Watch learns which devices are on your home network, and when they
come and go, without ever logging into them or pulling data from them.
It records only what the network itself reveals:

  * presence — an ICMP ping sweep of your local /24 (who answers)
  * announcements — devices' own mDNS (224.0.0.251:5353) and SSDP
    (239.255.255.250:1900) broadcasts, listened to passively
  * a light open-port check on a fixed list of common ports, run once
    when a device is first registered (a bare TCP connect — no login
    attempts, no data exchanged)

Records live in a records directory (default ./lan-watch-records,
override with --records-dir or the LAN_WATCH_HOME environment variable):

  devices.json  — registry: ip -> {first_seen, last_seen, ports, names,
                  services, announcements}
  events.jsonl  — JOIN / LEAVE / ANNOUNCE lines with timestamps
  watch.log     — daemon sweep summaries

Usage:
  python3 lan_watch.py --once [--listen SECONDS]     # one pass, then exit
  python3 lan_watch.py --daemon [--interval SEC]     # background watcher
  python3 lan_watch.py --records-dir PATH ...        # where records live

Run it only on networks you own or are authorized to monitor.
Standard library only. Requires Python 3 and a `ping` command on PATH.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

__version__ = "1.0.0"

DEFAULT_RECORDS_DIR = Path("lan-watch-records")
PORTS = [22, 53, 80, 443, 445, 3389, 8000, 8080]
MISS_LIMIT = 2  # consecutive absent sweeps before a LEAVE is recorded

_records_dir: Path | None = None


def configure(records_dir) -> None:
    """Set the records directory (used by --records-dir and by tests)."""
    global _records_dir
    _records_dir = Path(records_dir).expanduser()


def records_dir() -> Path:
    """Resolve the records directory: explicit setting, then the
    LAN_WATCH_HOME environment variable, then ./lan-watch-records."""
    global _records_dir
    if _records_dir is None:
        env = os.environ.get("LAN_WATCH_HOME")
        _records_dir = Path(env).expanduser() if env else DEFAULT_RECORDS_DIR
    return _records_dir


def devices_file() -> Path:
    return records_dir() / "devices.json"


def events_file() -> Path:
    return records_dir() / "events.jsonl"


def log_file() -> Path:
    return records_dir() / "watch.log"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    print(line, flush=True)
    records_dir().mkdir(parents=True, exist_ok=True)
    with log_file().open("a") as f:
        f.write(line + "\n")


def event(kind: str, ip: str, detail: str = "") -> None:
    records_dir().mkdir(parents=True, exist_ok=True)
    with events_file().open("a") as f:
        f.write(json.dumps({"ts": now(), "kind": kind, "ip": ip,
                            "detail": detail}) + "\n")


def load_devices() -> dict:
    path = devices_file()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_devices(devices: dict) -> None:
    records_dir().mkdir(parents=True, exist_ok=True)
    devices_file().write_text(json.dumps(devices, indent=1, sort_keys=True))


def source_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    finally:
        s.close()


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c1", "-W1", ip],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def sweep(base: str) -> set:
    # Throttled on purpose: a modest worker pool keeps the sweep gentle —
    # slower than a process storm, but the watcher (and the host it runs
    # on) stays healthy, and the network is not flooded with processes.
    hosts = [f"{base}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(ping, hosts))
    return {h for h, ok in zip(hosts, results) if ok}


def port_open(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=1):
            return True
    except OSError:
        return False


def check_ports(ip: str) -> list:
    return [p for p in PORTS if port_open(ip, p)]


# ---------------- passive announcement listeners ----------------

_printable = re.compile(rb"[ -~]{4,}")


def strings_from(data: bytes) -> list:
    return [s.decode("ascii", "replace")
            for s in _printable.findall(data)]


def listen(group: str, port: int, seconds: float, sink: dict,
           lock: threading.Lock) -> None:
    """Join a multicast group and record what devices announce."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                         socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", port))
        mreq = socket.inet_aton(group) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        log(f"listener {group}:{port} unavailable: {e}")
        return
    sock.settimeout(2)
    end = time.time() + seconds
    while time.time() < end:
        try:
            data, (ip, _) = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        if group.startswith("239."):  # SSDP: header text
            text = data.decode("utf-8", "replace")
            keep = [ln.strip() for ln in text.splitlines()
                    if ln.lower().startswith(("server:", "st:", "usn:",
                                              "location:", "nt:"))]
            payload = " | ".join(keep) or text.splitlines()[0:1]
        else:  # mDNS: pull readable names/services out of the packet
            strs = strings_from(data)
            keep = [s for s in strs
                    if "._tcp" in s or "._udp" in s or ".local" in s]
            payload = " | ".join(sorted(set(keep)))
        if payload:
            with lock:
                sink.setdefault(ip, []).append(str(payload))
    sock.close()


def run_listeners(seconds: float) -> dict:
    sink: dict = {}
    lock = threading.Lock()
    threads = [
        threading.Thread(target=listen,
                         args=("224.0.0.251", 5353, seconds, sink, lock)),
        threading.Thread(target=listen,
                         args=("239.255.255.250", 1900, seconds, sink, lock)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sink


# ---------------- main passes ----------------

def one_pass(listen_seconds: float) -> dict:
    src = source_ip()
    base = ".".join(src.split(".")[:3])
    heard = run_listeners(listen_seconds) if listen_seconds > 0 else {}
    live = sweep(base)
    devices = load_devices()
    for ip in sorted(live):
        entry = devices.setdefault(ip, {"first_seen": now(), "misses": 0})
        if not entry.get("_present"):
            event("JOIN", ip, "seen in sweep")
        entry["last_seen"] = now()
        entry["_present"] = True
        entry["misses"] = 0
        if "ports" not in entry:
            entry["ports"] = check_ports(ip)
    for ip, entry in devices.items():
        if ip not in live and entry.get("_present"):
            entry["misses"] = entry.get("misses", 0) + 1
            if entry["misses"] >= MISS_LIMIT:
                entry["_present"] = False
                event("LEAVE", ip,
                      f"absent {entry['misses']} consecutive sweeps")
    for ip, notes in heard.items():
        entry = devices.setdefault(ip, {"first_seen": now(), "misses": 0})
        known = entry.setdefault("announcements", [])
        for note in notes:
            if note not in known:
                known.append(note)
                event("ANNOUNCE", ip, note[:300])
        services = sorted({part for note in known
                           for part in note.split(" | ")
                           if "._tcp" in part or "._udp" in part})
        if services:
            entry["services"] = services
    save_devices(devices)
    present = sum(1 for e in devices.values() if e.get("_present"))
    log(f"pass complete: src={src} live={len(live)} registered="
        f"{len(devices)} present={present} announced={len(heard)}")
    return devices


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Passive presence monitor for your own LAN.")
    ap.add_argument("--once", action="store_true",
                    help="run one pass, then exit (the default)")
    ap.add_argument("--daemon", action="store_true",
                    help="keep watching in the foreground")
    ap.add_argument("--listen", type=float, default=90,
                    help="seconds of passive listening per pass")
    ap.add_argument("--interval", type=int, default=300,
                    help="daemon sweep interval seconds")
    ap.add_argument("--records-dir", default=None,
                    help="where records live (default: $LAN_WATCH_HOME or "
                         "./lan-watch-records)")
    args = ap.parse_args()
    if args.records_dir:
        configure(args.records_dir)
    records_dir().mkdir(parents=True, exist_ok=True)
    if args.daemon:
        log(f"daemon start (interval {args.interval}s, listen "
            f"{args.listen}s per pass)")
        while True:
            try:
                one_pass(args.listen)
            except Exception as e:  # keep the watcher alive
                log(f"pass error: {e!r}")
            time.sleep(args.interval)
    else:
        one_pass(args.listen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
