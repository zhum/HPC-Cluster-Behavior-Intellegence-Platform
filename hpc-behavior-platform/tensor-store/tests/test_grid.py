from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from hypothesis import given, settings, strategies as st

from tensor_store.grid import build_grid, reindex_and_ffill, resample_to_grid


def test_build_grid_length_and_spacing():
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15 * 20)
    grid = build_grid(start, end, resolution_s=15)
    assert len(grid) == 20
    deltas = np.diff(grid.values).astype("timedelta64[s]").astype(int)
    assert (deltas == 15).all()


def test_ffill_limit_stops_at_boundary():
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15 * 6)
    # single reading at t=0, then a gap for the rest of the window
    df = pd.DataFrame(
        {
            "ts": [start],
            "node_id": ["node-0"],
            "metric": ["cpu.utilization"],
            "value": [42.0],
        }
    )
    df_grid = resample_to_grid(df, start, end, resolution_s=15, ffill_limit=2)
    values = df_grid.sort_values("ts")["value"].to_numpy()
    # t=0: exact raw reading (its own grid bucket). t=1,2: forward-filled
    # (limit=2). t=3+: beyond the fill limit -> NaN.
    assert values[0] == 42.0
    assert values[1] == 42.0
    assert values[2] == 42.0
    assert np.isnan(values[3])
    assert np.isnan(values[4])
    assert np.isnan(values[5])


@given(
    n_points=st.integers(min_value=1, max_value=50),
    resolution_s=st.sampled_from([15, 60, 300]),
)
@settings(max_examples=25, deadline=None)
def test_grid_alignment_property(n_points, resolution_s):
    """resample_to_grid always returns exactly len(grid) rows per (node,metric),
    and every output timestamp is one of the exact grid points (property from
    v2 Phase 2 spec: 'grid alignment property tests (hypothesis)')."""
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=resolution_s * n_points)
    grid = build_grid(start, end, resolution_s)

    # single raw reading somewhere in the window, not necessarily on the grid
    raw_ts = start + timedelta(seconds=resolution_s * 0.5) if n_points > 0 else start
    df = pd.DataFrame(
        {
            "ts": [raw_ts],
            "node_id": ["node-0"],
            "metric": ["m"],
            "value": [1.0],
        }
    )

    df_grid = resample_to_grid(df, start, end, resolution_s)
    assert len(df_grid) == len(grid)
    assert set(df_grid["ts"]) <= set(grid)


def test_reindex_and_ffill_matches_resample_on_pregridded_input():
    """reindex_and_ffill (the SQL-pushdown path, input already floor-bucketed
    and deduped) must produce identical output to resample_to_grid (the
    raw-input path) when given the same data already on-grid.
    """
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15 * 6)
    df = pd.DataFrame(
        {
            "ts": [start],
            "node_id": ["node-0"],
            "metric": ["cpu.utilization"],
            "value": [42.0],
        }
    )
    via_resample = resample_to_grid(df, start, end, resolution_s=15, ffill_limit=2)
    via_reindex = reindex_and_ffill(df, start, end, resolution_s=15, ffill_limit=2)
    pd.testing.assert_frame_equal(
        via_resample.sort_values(["node_id", "metric", "ts"]).reset_index(drop=True),
        via_reindex.sort_values(["node_id", "metric", "ts"]).reset_index(drop=True),
    )


def test_reindex_and_ffill_empty_input():
    start = datetime(2026, 1, 1)
    end = start + timedelta(seconds=15 * 6)
    empty = pd.DataFrame(columns=["ts", "node_id", "metric", "value"])
    out = reindex_and_ffill(empty, start, end, resolution_s=15)
    assert list(out.columns) == ["ts", "node_id", "metric", "value"]
    assert len(out) == 0
