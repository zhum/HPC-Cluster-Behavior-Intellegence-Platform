"""Smoke-test / benchmark get_tensor() against a live ClickHouse instance.

Usage:
    python bench_get_tensor.py --minutes 5 --resolution 15
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone

from tensor_store.api import TensorRequest, get_tensor
from tensor_store.cache import DiskCache
from tensor_store.loader import get_client


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--password", default="devpass")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--resolution", type=int, default=15)
    args = ap.parse_args()

    client = get_client(host=args.host, port=args.port, password=args.password)
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(minutes=args.minutes)

    request = TensorRequest(start=start, end=end, resolution_s=args.resolution)
    cache = DiskCache(root=__import__("pathlib").Path("/tmp/tensor-store-bench-cache"))

    t0 = time.perf_counter()
    bundle = get_tensor(request, client=client, cache=cache, use_cache=True)
    cold_s = time.perf_counter() - t0
    print(
        f"COLD  shape={bundle.X.shape} nodes={len(bundle.nodes)} "
        f"metrics={len(bundle.metrics)} inactive={len(bundle.inactive_nodes)} "
        f"null_segments={len(bundle.null_segments)} time={cold_s:.2f}s"
    )

    t0 = time.perf_counter()
    bundle2 = get_tensor(request, client=client, cache=cache, use_cache=True)
    warm_s = time.perf_counter() - t0
    print(f"WARM  shape={bundle2.X.shape} time={warm_s:.3f}s (speedup {cold_s / warm_s:.0f}x)")


if __name__ == "__main__":
    main()
