#!/usr/bin/env python3
"""Smoke test for lan_watch.py — pure functions only, no network use.

Exercises registry load/save, event appending, and announcement-string
extraction inside a temporary records directory.

Run:  python3 test_lan_watch.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lan_watch


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        lan_watch.configure(tmp)

        # Records paths resolve inside the configured directory.
        assert lan_watch.records_dir() == tmp
        assert lan_watch.devices_file() == tmp / "devices.json"
        assert lan_watch.events_file() == tmp / "events.jsonl"

        # Empty registry loads as {}.
        assert lan_watch.load_devices() == {}

        # Save / load roundtrip (documentation-range IP, RFC 5737).
        registry = {
            "192.0.2.10": {
                "first_seen": lan_watch.now(),
                "last_seen": lan_watch.now(),
                "ports": [80, 443],
                "misses": 0,
            }
        }
        lan_watch.save_devices(registry)
        assert (tmp / "devices.json").exists()
        assert lan_watch.load_devices() == registry

        # A corrupt registry file loads as {} instead of raising.
        (tmp / "devices.json").write_text("{not json")
        assert lan_watch.load_devices() == {}

        # Event append writes one parseable JSON line per event.
        lan_watch.event("JOIN", "192.0.2.10", "seen in sweep")
        lan_watch.event("ANNOUNCE", "192.0.2.10", "printer._tcp")
        lines = (tmp / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["kind"] == "JOIN" and first["ip"] == "192.0.2.10"
        assert first["detail"] == "seen in sweep" and first["ts"]
        second = json.loads(lines[1])
        assert second["kind"] == "ANNOUNCE"

        # strings_from pulls printable runs (service names) out of a
        # raw announcement packet.
        packet = b"\x00\x01MyPrinter\x07_printer\x04_tcp\x05local\x00zz"
        found = lan_watch.strings_from(packet)
        assert any("_tcp" in s for s in found), found
        assert lan_watch.strings_from(b"\x00\x01\x02") == []

    print("lan_watch smoke test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
