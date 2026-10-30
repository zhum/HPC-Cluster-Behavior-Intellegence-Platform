"""Read /sys/class/infiniband counters and publish per-node rates to Redpanda topic `ib.metrics`.

Message: {"ts": ISO-8601, "node_id": str, "metric": "ib.<counter>", "value": per-second rate}
-- one per counter per poll, flat so ClickHouse's Kafka engine reads it as JSONEachRow
(clickhouse/sink.sql).

Only custom OTel-adjacent collector permitted by v2 spec (node_exporter's own
infiniband collector doesn't expose retries/congestion/symbol_errors/link_downed
uniformly across HCA vendors, so we read sysfs directly).
"""
from __future__ import annotations

import glob
import json
import os
import socket
import time
from datetime import datetime, timezone

from kafka import KafkaProducer

KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS", "redpanda:9092").split(",")
TOPIC = "ib.metrics"
POLL_INTERVAL_S = 15
SYSFS_ROOT = "/sys/class/infiniband"

COUNTERS = {
    "symbol_errors": "symbol_error",
    "link_downed": "link_downed",
    "retries": "local_link_integrity_errors",
    "congestion": "excessive_buffer_overrun_errors",
}


def read_counter(hca_path: str, port: str, counter_file: str) -> int | None:
    path = os.path.join(hca_path, "ports", port, "counters", counter_file)
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def read_counters() -> dict[tuple[str, str, str], int]:
    """Cumulative counters keyed by (hca, port, metric)."""
    counters = {}
    for hca_path in glob.glob(f"{SYSFS_ROOT}/*"):
        hca = os.path.basename(hca_path)
        ports_dir = os.path.join(hca_path, "ports")
        if not os.path.isdir(ports_dir):
            continue
        for port in os.listdir(ports_dir):
            for metric_name, counter_file in COUNTERS.items():
                value = read_counter(hca_path, port, counter_file)
                if value is not None:
                    counters[(hca, port, metric_name)] = value
    return counters


def to_rates(
    prev: dict[tuple[str, str, str], int], curr: dict[tuple[str, str, str], int], dt_s: float
) -> dict[str, float]:
    """Per-second rate per metric, summed over all HCAs/ports, so every node exposes the same
    few metrics regardless of HCA count. A port whose counter went backwards (reset / HCA
    reload) or is new since the last poll is left out of that interval's sum."""
    deltas: dict[str, int] = {}
    for key, value in curr.items():
        before = prev.get(key)
        if before is None or value < before:
            continue
        deltas[key[2]] = deltas.get(key[2], 0) + value - before
    return {f"ib.{metric}": d / dt_s for metric, d in deltas.items()}


def main() -> None:
    node_id = os.environ.get("NODE_ID", socket.gethostname())
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    prev: dict[tuple[str, str, str], int] = {}
    prev_t = 0.0
    while True:
        try:
            curr, now = read_counters(), time.monotonic()
            if prev:  # first poll only primes the baseline
                ts = datetime.now(timezone.utc).isoformat()
                for metric, value in to_rates(prev, curr, now - prev_t).items():
                    producer.send(
                        TOPIC, {"ts": ts, "node_id": node_id, "metric": metric, "value": value}
                    )
                producer.flush()
            prev, prev_t = curr, now
        except Exception as exc:  # sysfs absent on non-IB hosts; keep polling
            print(f"[ib-poller] collect failed: {exc}")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
