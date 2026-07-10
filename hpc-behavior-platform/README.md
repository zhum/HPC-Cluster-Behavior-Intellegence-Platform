# HPC Cluster Behavior Intelligence Platform

Monorepo implementing arXiv:2604.11965 ("Understanding Large-Scale HPC System
Behavior Through Cluster-Based Visual Analytics"). See
`HPC_Cluster_Behavior_Intelligence_Platform_v2.md` at repo root for the full
corrected spec — v2 supersedes v1; read v2's "KEY CORRECTIONS" section first.

```
telemetry-agent/   Phase 1: node-side collection config (thin)
ingest-infra/       Phase 1: docker-compose stack - Redpanda, ClickHouse, OTel, Grafana
tensor-store/       Phase 2: tensor materialization + preprocessing (not started)
analysis-core/      Phases 3-4: MulTiDR, ccPCA, mrDMD, baselines (not started)
analysis-api/       Phase 5: FastAPI + Redis cache (not started)
behavior-ui/        Phase 6: React/TS four-view interface (not started)
evaluation/         Phase 7: cluster-quality benchmarks (not started)
```

## Status

**Phase 1 (Telemetry Foundation): scaffolded.**

- `ingest-infra/docker-compose.yml` — Redpanda (3 topics), ClickHouse (schema
  in `clickhouse/schema.sql`), OTel Collector gateway, Grafana (provisioned
  datasource + live-metrics dashboard).
- `ingest-infra/tools/synth_nodes.py` — synthetic load generator for local dev
  (`--nodes`, `--metrics`, `--interval`, `--kill-after`/`--kill-fraction` to
  test null-segment detection).
- `ingest-infra/tools/ib_poller.py`, `slurm_poller.py` — the two permitted
  custom collectors (sysfs IB counters; centralized slurmrestd polling).
- `ingest-infra/tools/test_null_segments.py` — acceptance test for the
  downtime/null-segment detection milestone.

Next: `docker compose up` in `ingest-infra/`, verify Grafana shows live data,
run the null-segment test, then move to Phase 2 (tensor-store).

## Global conventions

- Python 3.11+, `pyproject.toml` per package, `ruff` + `mypy --strict` on
  `analysis-core`.
- Every analysis function is pure (tensor in, arrays out), unit-tested on
  synthetic fixtures before integration.
- Deterministic by default: `random_state=42` everywhere.
- All stage outputs serializable (numpy `.npz` / Arrow) for caching.
