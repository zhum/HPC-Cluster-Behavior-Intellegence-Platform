"""Read /sys/class/infiniband counters and publish to Redpanda topic `ib.metrics`.

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


def collect(node_id: str) -> list[dict]:
    records = []
    ts = datetime.now(timezone.utc).isoformat()
    for hca_path in glob.glob(f"{SYSFS_ROOT}/*"):
        hca = os.path.basename(hca_path)
        ports_dir = os.path.join(hca_path, "ports")
        if not os.path.isdir(ports_dir):
            continue
        for port in os.listdir(ports_dir):
            for metric_name, counter_file in COUNTERS.items():
                value = read_counter(hca_path, port, counter_file)
                if value is None:
                    continue
                records.append(
                    {
                        "ts": ts,
                        "node_id": node_id,
                        "hca": hca,
                        "port": port,
                        "metric": metric_name,
                        "value": value,
                    }
                )
    return records


def main() -> None:
    node_id = os.environ.get("NODE_ID", socket.gethostname())
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    while True:
        try:
            records = collect(node_id)
            for r in records:
                producer.send(TOPIC, r)
            producer.flush()
        except Exception as exc:  # sysfs absent on non-IB hosts; keep polling
            print(f"[ib-poller] collect failed: {exc}")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
