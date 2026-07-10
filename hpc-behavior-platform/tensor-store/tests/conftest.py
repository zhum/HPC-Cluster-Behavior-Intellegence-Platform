from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest


@pytest.fixture
def synthetic_long_df() -> pd.DataFrame:
    """3 nodes x 2 metrics x 10 timesteps at 15s resolution, fully populated,
    deterministic values so pivoting can be checked exactly.
    """
    start = datetime(2026, 1, 1, 0, 0, 0)
    nodes = ["node-0", "node-1", "node-2"]
    metrics = ["cpu.utilization", "memory.used"]
    rows = []
    for n_i, node in enumerate(nodes):
        for m_i, metric in enumerate(metrics):
            for t_i in range(10):
                ts = start + timedelta(seconds=15 * t_i)
                value = n_i * 100 + m_i * 10 + t_i
                rows.append({"ts": ts, "node_id": node, "metric": metric, "value": float(value)})
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_window() -> tuple[datetime, datetime]:
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = start + timedelta(seconds=15 * 10)
    return start, end
