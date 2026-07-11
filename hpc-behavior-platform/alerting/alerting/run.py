"""CLI: scheduled headless anomaly-alerting runs.

    python -m alerting.run --lookback-s 3600 --resolution 60 --k 4 --band 2h \
        --webhook-url https://example.com/hook --interval-s 300
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

from tensor_store.loader import get_client as get_tensor_client

from alerting.scheduler import Z_THRESHOLD, run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 8 alerting scheduler")
    parser.add_argument("--lookback-s", type=int, default=3600)
    parser.add_argument("--resolution", type=int, default=60)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--band", default="2h", choices=["5m", "30m", "2h", "24h", "7d"])
    parser.add_argument("--z-threshold", type=float, default=Z_THRESHOLD)
    parser.add_argument("--webhook-url", default=None)
    parser.add_argument("--interval-s", type=int, default=0, help="0 = run once and exit")
    parser.add_argument("--clickhouse-host", default="localhost")
    parser.add_argument("--clickhouse-port", type=int, default=8123)
    parser.add_argument("--clickhouse-password", default="devpass")
    args = parser.parse_args()

    client = get_tensor_client(
        host=args.clickhouse_host, port=args.clickhouse_port, password=args.clickhouse_password
    )

    def tick() -> None:
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(seconds=args.lookback_s)
        report = run_once(
            tensor_client=client,
            alert_client=client,
            start=start,
            end=end,
            resolution_s=args.resolution,
            k=args.k,
            band=args.band,
            webhook_url=args.webhook_url,
            z_threshold=args.z_threshold,
        )
        print(
            f"[alerting] {end.isoformat()}: checked {report.clusters_checked} clusters, "
            f"{report.metrics_checked} metric-checks, {len(report.new_anomalies)} new anomalies, "
            f"webhook_delivered={report.webhook_delivered}"
        )

    if args.interval_s <= 0:
        tick()
        return

    while True:
        tick()
        time.sleep(args.interval_s)


if __name__ == "__main__":
    main()
