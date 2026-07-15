# HPC Cluster Behavior Intelligence Platform

Monorepo implementing arXiv:2604.11965 ("Understanding Large-Scale HPC System
Behavior Through Cluster-Based Visual Analytics"). See
`HPC_Cluster_Behavior_Intelligence_Platform_v2.md` at repo root for the full
corrected spec — v2 supersedes v1; read v2's "KEY CORRECTIONS" section first.

```
telemetry-agent/   Phase 1: node-side collection config (thin)
ingest-infra/       Phase 1: docker-compose stack - Redpanda, ClickHouse, OTel, Grafana (+ HA variant)
tensor-store/       Phase 2: tensor materialization + preprocessing
analysis-core/      Phases 3-4: MulTiDR, ccPCA, mrDMD, baselines, z-scores
analysis-api/       Phase 5: FastAPI + Redis cache, sessions, saved analyses
behavior-ui/        Phase 6: React/TS four-view interface + Playwright e2e
evaluation/         Phase 7: cluster-quality benchmarks, fault injection, DR ablation
alerting/           Phase 8: scheduled baseline-drift alerting (beyond the paper)
```

## Status

**Phases 1-7 implemented; Phase 8 (beyond-the-paper extensions) largely done.**

- Phase 1 ingestion stack (`ingest-infra/`): Redpanda, ClickHouse (+ Keeper HA
  variant in `docker-compose.ha.yml`), OTel Collector, Grafana; custom
  collectors `ib_poller.py` / `slurm_poller.py`; null-segment acceptance test.
- Phase 2 (`tensor-store/`): N×M×T tensor materialization from ClickHouse with
  uniform-grid resampling, null/downtime handling, normalization, `.npz` cache.
- Phases 3-4 (`analysis-core/`): MulTiDR (PCA-over-time → UMAP), k-means +
  ccPCA explanations, mrDMD frequency-band z-scores with IQR-window baselines,
  incremental refresh (Procrustes + Hungarian relabeling).
- Phase 5 (`analysis-api/`): FastAPI session/inter/intra/raw/jobs routers,
  Redis-backed caching, request envelope limits, saved analyses.
- Phase 6 (`behavior-ui/`): the paper's four coordinated views (Time Domain,
  Node Similarity, Metric Reading, Node Behavior) with lasso, k-recompute,
  baseline brushing; Playwright e2e suite.
- Phase 7 (`evaluation/`): quality benchmark (planted-cluster ARI gate), DR
  ablation, fault injection (all four fault types pass the recall>=0.9 gate),
  reports under `evaluation/reports/`.
- Phase 8: HA infra, multi-user sessions + saved analyses, alerting service;
  research-track contrastive embeddings gated behind the `research` extra.

See `docs/test-plan-hardware-oci.md` for the real-hardware/OCI GPU test plan.

## Global conventions

- Python 3.11+, `pyproject.toml` per package, `ruff` + `mypy --strict` on
  `analysis-core`.
- Every analysis function is pure (tensor in, arrays out), unit-tested on
  synthetic fixtures before integration.
- Deterministic by default: `random_state=42` everywhere.
- All stage outputs serializable (numpy `.npz` / Arrow) for caching.
