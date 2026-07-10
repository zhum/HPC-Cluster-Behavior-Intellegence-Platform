"""Integration test: killing a synthetic node produces a detectable null
segment (missing rows) in ClickHouse. Phase 1 acceptance criterion.

Run against a live docker-compose stack:
    docker compose up -d clickhouse
    python tools/test_null_segments.py
"""
from __future__ import annotations

import subprocess
import sys
import time

import clickhouse_connect

NODES = 20
METRICS = 5
INTERVAL = 2
KILL_AFTER = 10
KILL_FRACTION = 0.2
DURATION = 30


def main() -> int:
    client = clickhouse_connect.get_client(host="localhost", port=8123, password="devpass")

    proc = subprocess.Popen(
        [
            sys.executable, "synth_nodes.py",
            "--nodes", str(NODES), "--metrics", str(METRICS),
            "--interval", str(INTERVAL), "--duration", str(DURATION),
            "--kill-after", str(KILL_AFTER), "--kill-fraction", str(KILL_FRACTION),
            "--clickhouse-host", "localhost",
        ],
        cwd="tools" if not __file__.endswith("tools/test_null_segments.py") else ".",
    )
    proc.wait(timeout=DURATION + 15)

    time.sleep(2)  # allow final inserts to flush

    result = client.query(
        """
        SELECT node_id, max(ts) AS last_seen
        FROM metrics_raw
        WHERE ts > now() - INTERVAL 5 MINUTE
        GROUP BY node_id
        ORDER BY last_seen ASC
        """
    )
    rows = result.result_rows
    assert len(rows) > 0, "expected some node data"
    print("Nodes ordered by last-seen timestamp (earliest = candidates for killed set):")
    for node_id, last_seen in rows[:5]:
        print(f"  {node_id}: last_seen={last_seen}")

    # Killed nodes stop reporting ~(DURATION - KILL_AFTER) seconds before the
    # last surviving node's final timestamp -> detectable gap in last_seen.
    latest = max(r[1] for r in rows)
    gap_s = (DURATION - KILL_AFTER) * 0.5  # half the post-kill window, as margin
    stale = [r for r in rows if (latest - r[1]).total_seconds() > gap_s]
    assert stale, (
        f"expected at least one node with last_seen >{gap_s}s behind latest={latest}; "
        f"got spread={[(r[0], (latest - r[1]).total_seconds()) for r in rows]}"
    )
    print(f"PASS: {len(stale)} node(s) show a null segment after simulated kill "
          f"(>{gap_s:.0f}s behind latest last_seen).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
