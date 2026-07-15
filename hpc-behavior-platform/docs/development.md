# Development Guide

## Repo layout

Monorepo, `hpc-behavior-platform/` root. Each Python package (`telemetry-agent` config aside) is independently versioned: own `pyproject.toml`, own `.venv/`, own `tests/`. There is no root Makefile or single install script — set each package up individually. See [Overview § Package map](./overview.md#package-map).

## Conventions

- Python ≥3.11, setuptools build backend.
- `ruff` everywhere: line length 100, target `py311`. Config lives inline in each package's `pyproject.toml` under `[tool.ruff]`, not a shared file.
- `mypy --strict` mandated on `analysis-core`, `analysis-api`, and `tensor-store` (the packages with public numeric APIs). Not enforced on `evaluation`/`alerting`.
- `random_state=42` everywhere any algorithm has one — determinism is load-bearing for the quality gates below and for reproducing bug reports.
- Frontend: `oxlint` for linting, TypeScript strict via `tsc -b`.

## Setting up a package

```bash
cd hpc-behavior-platform/<package>
pip install -e ".[dev]"
pytest
```

Do this per package you're touching (`analysis-core`, `analysis-api`, `tensor-store`, `evaluation`, `alerting`).

Frontend:

```bash
cd hpc-behavior-platform/behavior-ui
npm install
npm run dev      # vite dev server, :5173
npm run lint      # oxlint
npm run build      # tsc -b && vite build
```

## Testing

Every Python package has its own `tests/`, run with `pytest` inside that package's venv — no live ClickHouse/Redis required for `analysis-api` tests, which override `app.state.session_store` / `stage_cache` / `clickhouse_client` directly (see `analysis_api/main.py` docstring) and use `fakeredis`/`httpx`.

| Package | Test dir | Notes |
|---|---|---|
| `analysis-core` | `tests/` | `test_baseline`, `test_ccpca`, `test_clustering`, `test_incremental`, `test_mrdmd`, `test_multidr`, `test_pipeline`, `test_quality`, `test_zscores`; uses `hypothesis` for property tests |
| `analysis-api` | `tests/` | `test_analyses`, `test_inter`, `test_intra`, `test_raw_and_jobs`, `test_session`; integration tests via `httpx` against mocked backends |
| `tensor-store` | `tests/` | `test_api`, `test_cache`, `test_grid`, `test_normalize`, `test_nulls`, `test_tensor`; `hypothesis` for grid-alignment properties |
| `evaluation` | `tests/` | `test_dr_ablation`, `test_fault_injection`, `test_ground_truth`, `test_quality_benchmark`, `test_research_contrastive` |
| `alerting` | `tests/` | `test_baseline_state`, `test_scheduler`, `test_store`, `test_webhook` |
| `behavior-ui` | `e2e/` | Playwright: `acceptance.spec.ts`, `saved-analyses.spec.ts`; config `playwright.config.ts`, baseURL `http://localhost:5173`, 60s timeout, trace-on-failure |

Run e2e tests against a live dev stack + running frontend:

```bash
cd hpc-behavior-platform/behavior-ui
npx playwright test
```

**No CI config exists in the repo** (no `.github/workflows`). Quality gates below are enforced by convention/review, not automated CI, though `evaluation/README.md` references CI enforcement as an intended goal — treat that as aspirational, not current.

### Quality gates (hard requirements, checked by tests)

- **Phase 3 (inter-node clustering)**: ships only if planted-cluster ARI > 0.9 and beats a PCA-only baseline. Achieved: MulTiDR ARI 1.000 vs PCA-only 0.716.
- **Phase 4 (intra-node anomaly detection)**: ships only if injected anomalies are recovered at recall ≥ 0.9 for `|z| ≥ 3`. Met for `dead_node` and `cpu_steal`. **Not met** for `memory_leak_ramp` (a monotonic ramp is a poor fit for DMD, which models oscillatory/exponential dynamics) or `ib_error_burst` (a short impulse relative to mrDMD window sizes). These are real, documented limitations of DMD, not bugs — see `evaluation/reports/fault_injection.md`.

## Regenerating evaluation reports

```bash
cd hpc-behavior-platform/evaluation
python -m evaluation.run_all
```

Rewrites `evaluation/reports/{dr_ablation,fault_injection,quality_benchmark,research_contrastive}.md`.

## Analysis CLIs (useful for local iteration without the API/UI)

```bash
python -m analysis_core.inter.run --start ... --end ... --resolution 60 --k 4
python -m analysis_core.intra.run --start ... --end ... --resolution 60 --k 4 --cluster 0 --band 2h
python -m alerting.run --lookback-s 3600 --resolution 60 --k 4 --band 2h --webhook-url ... --interval-s 300
```

All three accept `--clickhouse-host/--clickhouse-port/--clickhouse-password` (default `localhost:8123` / `devpass`).

## Working on the frontend

State: `behavior-ui/src/store/useStore.ts` (Zustand) — this is where cross-view coordination lives; if you're adding a new interaction between views, it goes through this store, not component props.

API client: `behavior-ui/src/api/client.ts` / `types.ts`.

Four view components: `TimeDomainView`, `NodeSimilarityView`, `MetricSelectionPanel` + `ClusterReadingSummary` + `ReadingInspection` (the three-part Metric Reading view), `NodeBehaviorView`, plus `SavedAnalysesPanel`.

## Working on `analysis-core`

Pure-function library — no I/O, no framework dependencies. This is the package with `mypy --strict` most strictly enforced; keep new code typed accordingly. If you're touching `zscores.py`, note there's an accepted-but-not-yet-adopted plan to parallelize `compute_zscores` across metrics (`docs/plan-zscore-parallelization.md`) — deferred until there's benchmark evidence it's worth the process-pool overhead. Don't implement it speculatively.

## Legacy/historical files — don't build on these

Root-level `observability-agent/`, `0-docker-compose.yml`, `0-init.sh`, `Phase0.md`/`Phase0.md.alt`, and `HPC Cluster Behavior Intelligence Platform_v1.md` predate the current (v2) architecture and are superseded by `ingest-infra/` and `HPC_Cluster_Behavior_Intelligence_Platform_v2.md` respectively. They're kept for history; don't extend them.
