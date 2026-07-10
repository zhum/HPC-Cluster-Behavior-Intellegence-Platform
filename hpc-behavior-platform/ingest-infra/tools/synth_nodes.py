"""Synthetic node load generator for local dev / acceptance testing.

Publishes fake CPU/mem/net/gpu/ib metrics for N nodes at a fixed sample
interval straight to ClickHouse (bypassing OTel/Redpanda for simplicity in
this dev tool -- the collector path is exercised separately via node_exporter/
DCGM containers). Supports killing individual synthetic nodes to verify the
null-segment detection path (Phase 1 acceptance criterion).

Usage:
    python synth_nodes.py --nodes 200 --metrics 50 --interval 15 \
        --clickhouse-host localhost --kill-after 120 --kill-fraction 0.05
"""
from __future__ import annotations

import argparse
import math
import random
import time
from datetime import datetime, timezone

import clickhouse_connect

BASE_METRICS = [
    "cpu.utilization", "cpu.load_avg", "cpu.context_switches", "cpu.interrupts",
    "memory.used", "memory.free", "memory.page_faults", "memory.swap",
    "network.tx_bytes", "network.rx_bytes", "network.drops", "network.retransmits",
    "storage.iops", "storage.throughput", "storage.latency",
    "gpu.utilization", "gpu.memory_used", "gpu.power", "gpu.temperature",
    "gpu.ecc_errors", "gpu.nvlink_tx", "gpu.nvlink_rx",
]


def build_metric_list(n_metrics: int) -> list[str]:
    metrics = list(BASE_METRICS)
    i = 0
    while len(metrics) < n_metrics:
        metrics.append(f"synthetic.extra_{i}")
        i += 1
    return metrics[:n_metrics]


def sample_value(metric: str, node_idx: int, t: float) -> float:
    phase = node_idx * 0.37
    base = 50 + 40 * math.sin(t / 300.0 + phase)
    noise = random.gauss(0, 3)
    if "error" in metric or "drops" in metric or "ecc" in metric:
        return max(0.0, random.gauss(0.1, 0.3))
    return max(0.0, base + noise)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=200)
    ap.add_argument("--metrics", type=int, default=50)
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--clickhouse-host", default="localhost")
    ap.add_argument("--clickhouse-port", type=int, default=8123)
    ap.add_argument("--clickhouse-password", default="devpass")
    ap.add_argument("--duration", type=float, default=0.0, help="0 = run forever")
    ap.add_argument("--kill-after", type=float, default=0.0,
                     help="seconds after which --kill-fraction of nodes go silent")
    ap.add_argument("--kill-fraction", type=float, default=0.0)
    args = ap.parse_args()

    node_ids = [f"node-{i:05d}" for i in range(args.nodes)]
    metrics = build_metric_list(args.metrics)

    client = clickhouse_connect.get_client(
        host=args.clickhouse_host, port=args.clickhouse_port,
        password=args.clickhouse_password,
    )

    killed: set[str] = set()
    start = time.monotonic()
    tick = 0
    while args.duration <= 0 or (time.monotonic() - start) < args.duration:
        now = time.monotonic() - start
        if args.kill_after > 0 and now >= args.kill_after and not killed:
            n_kill = int(len(node_ids) * args.kill_fraction)
            killed.update(random.sample(node_ids, n_kill))
            print(f"[synth] killing {n_kill} nodes: {sorted(killed)[:5]}...")

        ts = datetime.now(timezone.utc)
        rows = []
        for idx, node_id in enumerate(node_ids):
            if node_id in killed:
                continue
            for metric in metrics:
                rows.append((ts, node_id, metric, sample_value(metric, idx, now)))

        if rows:
            client.insert(
                "metrics_raw", rows, column_names=["ts", "node_id", "metric", "value"]
            )
        tick += 1
        if tick % 10 == 0:
            print(f"[synth] tick={tick} rows={len(rows)} alive={len(node_ids) - len(killed)}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
