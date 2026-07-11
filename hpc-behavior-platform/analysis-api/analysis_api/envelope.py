"""Analysis envelope limits: the pipelines are validated for N<=2000 nodes,
M<=500 metrics, T<=10000 timesteps. Requests outside this envelope 422
rather than silently running a slow/oversized job.
"""
from __future__ import annotations

from fastapi import HTTPException

MAX_NODES = 2000
MAX_METRICS = 500
MAX_TIMESTEPS = 10000


def enforce_envelope(n_nodes: int, n_metrics: int, n_timesteps: int) -> None:
    violations = []
    if n_nodes > MAX_NODES:
        violations.append(f"nodes={n_nodes} exceeds envelope max {MAX_NODES}")
    if n_metrics > MAX_METRICS:
        violations.append(f"metrics={n_metrics} exceeds envelope max {MAX_METRICS}")
    if n_timesteps > MAX_TIMESTEPS:
        violations.append(f"timesteps={n_timesteps} exceeds envelope max {MAX_TIMESTEPS}")
    if violations:
        raise HTTPException(status_code=422, detail="; ".join(violations))
