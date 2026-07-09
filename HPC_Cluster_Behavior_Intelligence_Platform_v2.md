# PROJECT: HPC Cluster Behavior Intelligence Platform

version: 2.0 (corrected against arXiv:2604.11965 full text)

objective: Faithfully implement the methodology of "Understanding Large-Scale HPC
System Behavior Through Cluster-Based Visual Analytics" (Austin, Shilpika, et al.)
as a production service, then optionally extend it toward streaming/real-time
operation (the paper's own stated future work).

references:
- arXiv:2604.11965 (primary)
- Reference implementation by the authors: https://github.com/VIDILabs/node-cluster-vis
  (consult for view layouts and parameter defaults; do not copy code verbatim)
- MulTiDR: Fujiwara et al., IEEE TVCG 27(2), 2021 (two-phase DR for tensor data)
- ccPCA: Fujiwara, Kwon, Ma, IEEE TVCG 26(1), 2020 (contrastive cluster explanation)
- mrDMD: Kutz, Fu, Brunton, SIAM J. Applied Dynamical Systems 15(2), 2016
- pydmd library (MrDMD class)

## KEY CORRECTIONS FROM v1 (read before implementing anything)

1. The paper's "two-phase dimensionality reduction" is **MulTiDR**:
   PCA across the TIME dimension (one PCA per metric slice, compressing each
   node's temporal pattern to a scalar) -> N×M matrix -> UMAP across the METRIC
   dimension -> N×2 embedding. It is NOT IncrementalPCA(64) -> UMAP.
2. The paper's "contrastive learning" is **ccPCA**, a linear contrastive method
   used to EXPLAIN clusters (which metrics make each cluster unique, one-vs-rest).
   There is NO deep encoder, NO InfoNCE, NO GPU training server, NO ONNX serving.
   Delete v1 Phase 4 entirely; it is replaced by an explainability module.
3. Clustering is **k-means** on the 2D UMAP embedding (default k=4, user-tunable
   in the UI), NOT HDBSCAN.
4. **mrDMD operates on RAW time series** of a user-selected {cluster, metrics,
   time range}, NOT on learned embeddings. Modes are filtered by frequency band
   using the mrDMD spectrum; z-scores are computed against baseline mrDMD modes.
5. Baselines are derived statistically (**IQR + longest in-range window, tiled**)
   and are **user-adjustable in the UI**. Baseline customization is a first-class
   requirement (paper R3/R4, Fig. 3), not an afterthought.
6. **Stage-level caching** is the paper's scalability mechanism (DR results cached;
   re-clustering / ccPCA / mrDMD re-run interactively in <10 ms after a cache hit,
   vs. 30–70 s cold). The system is an interactive analysis loop, not a batch
   anomaly pipeline.
7. The paper's system runs 1,600 nodes × 123 metrics × 1,096 timestamps on a
   laptop. Analysis compute is modest; the heavy infrastructure is only for
   telemetry ingestion/storage. Size servers accordingly.
8. Analysis operates on the data tensor **X ∈ R^{N×M×T}** (Node × Metric × Time)
   materialized from storage for a chosen time window — typically hours to a few
   days at 15–60 s resolution — not on the full ingestion firehose.

target_scale:
  nodes: 1,000–10,000 (ingestion); 200–2,000 per interactive analysis session
  metrics_per_node: 100–500
  ingestion_sampling_interval: 15 s default (per-metric configurable; this bounds
    ingestion at ~10k nodes × 500 metrics / 15 s ≈ 333k points/s worst case)
  analysis_tensor: N ≤ 2,000, M ≤ 500, T ≤ 10,000 per session (paper-validated
    envelope with caching; enforce via API limits)

repositories (monorepo or six repos; monorepo recommended for a single agent):

```
hpc-behavior-platform/
  telemetry-agent/        # Phase 1: node-side collection config (thin)
  ingest-infra/           # Phase 1: docker-compose / IaC for Redpanda, ClickHouse, OTel, Grafana
  tensor-store/           # Phase 2: tensor materialization + preprocessing library
  analysis-core/          # Phases 3–4: MulTiDR, ccPCA, mrDMD, baselines, metrics
  analysis-api/           # Phase 5: FastAPI + Redis cache
  behavior-ui/            # Phase 6: React/TS four-view interface
  evaluation/             # Phase 7: cluster-quality benchmarks, case-study replication
```

Global conventions for the implementing agent:
- Python 3.11+, `pyproject.toml` per package, `ruff` + `mypy --strict` on analysis-core.
- Every analysis function is pure (tensor in, arrays out) and unit-tested on
  synthetic fixtures BEFORE any integration work.
- Deterministic by default: `random_state=42` everywhere (paper uses this for UMAP).
- All stage outputs are serializable (numpy .npz / Arrow) so they can be cached.

---

## PHASE 1 — TELEMETRY FOUNDATION

goal: Collect and store node telemetry as queryable time series with explicit,
uniform sampling; track null-reading segments (needed by the Time Domain view).

servers (right-sized; add replicas only in Phase 8):
- ingest_server:  32 cpu / 128 GB / 2 TB NVMe  — OTel Collector (gateway), Redpanda (3-broker single-host dev, 3-node prod)
- storage_server: 32 cpu / 256 GB / 8 TB NVMe  — ClickHouse, Grafana
  NOTE: at 333k points/s with 15 s sampling, raw retention on 8 TB is ~30–60 days
  with ClickHouse compression. Set TTLs (below) accordingly and document the math
  in ingest-infra/README.md.

collection design (fixes to v1):
- Do NOT write custom psutil collectors. Use standard exporters scraped/pushed
  through the OTel Collector:
  - node_exporter (CPU, memory, network, disk, load)
  - NVIDIA DCGM-exporter (GPU util, memory, power, temp, ECC, NVLink)
  - InfiniBand: node_exporter's infiniband collector or a thin custom OTel
    receiver reading /sys/class/infiniband counters (retries, symbol errors,
    link_downed, congestion) — this is the ONLY custom collector permitted.
- Slurm data is collected CENTRALLY via slurmrestd (poll every 30 s), not per node.
  A small `slurm-poller` service (Python, ~200 lines) publishes to Redpanda topic
  `slurm.jobs`. Fields: job_id, user, partition, node_list, state, start, end,
  exit_code, priority. (Used in Phase 6 to reproduce the paper's job-priority and
  "not mapped to any jobs" findings.)
- Clock sync: require chrony/NTP on all nodes; the tensor builder (Phase 2)
  aligns to a global 15 s grid, so sub-second skew is acceptable.

redpanda_topics: otel.metrics, slurm.jobs, ib.metrics (drop otel.logs/events for now)

clickhouse schema (ingest-infra/clickhouse/schema.sql):

```sql
CREATE TABLE metrics_raw (
  ts        DateTime64(3),
  node_id   LowCardinality(String),
  metric    LowCardinality(String),
  value     Float64
) ENGINE = MergeTree
PARTITION BY toDate(ts)
ORDER BY (metric, node_id, ts)
TTL toDateTime(ts) + INTERVAL 45 DAY;

-- 1m rollup via materialized view (avg, min, max, count);
-- count=0 rows are how null segments are detected downstream.
CREATE MATERIALIZED VIEW metrics_1m ... ENGINE = AggregatingMergeTree ...
TTL 1 YEAR;

CREATE TABLE jobs (...) ORDER BY (start_time, job_id);
CREATE TABLE node_inventory (node_id, rack, cabinet, cage, partition, hardware_gen ...);
```

milestone / acceptance:
- `docker compose up` in ingest-infra brings up the full stack locally with a
  synthetic-node load generator (provide `tools/synth_nodes.py --nodes 200 --metrics 50`).
- Grafana dashboard shows live metrics; ClickHouse query
  `SELECT count() FROM metrics_raw WHERE ts > now() - 60` returns expected volume.
- Kill a synthetic node; its absence appears as missing rows (null segment) —
  verified by an integration test.

---

## PHASE 2 — TENSOR STORE (preprocessing library)

goal: Materialize the analysis tensor X ∈ R^{N×M×T} for a requested
{time_range, node_set, metric_set, resolution}, plus the null-segment table that
drives the Time Domain view.

package: tensor-store/tensor_store/

```
tensor_store/
  loader.py        # ClickHouse -> long dataframe (clickhouse-connect)
  grid.py          # resample to uniform grid (15s/1m/5m), forward-fill limit=2,
                   # beyond that leave NaN
  tensor.py        # pivot to numpy (N, M, T) + index objects (node_ids, metrics, times)
  nulls.py         # per (node, timestamp): all-metrics-null flag -> downtime segments
  normalize.py     # per-metric z-score or min-max across (N,T); config-driven
  cache.py         # content-addressed on-disk cache: key = sha256(request params);
                   # store .npz + json indexes
  api.py           # get_tensor(request: TensorRequest) -> TensorBundle
```

Key contracts:

```python
@dataclass(frozen=True)
class TensorRequest:
    start: datetime; end: datetime
    resolution_s: int           # 15 | 60 | 300
    nodes: list[str] | None     # None = all active
    metrics: list[str] | None

@dataclass
class TensorBundle:
    X: np.ndarray               # (N, M, T), NaN allowed
    nodes: list[str]; metrics: list[str]; times: np.ndarray
    null_segments: pd.DataFrame # node_id, seg_start, seg_end (all-metric nulls)
    coverage: np.ndarray        # (N, M) fraction of non-NaN — used for filtering
```

Rules:
- Metrics with coverage < 0.5 over the window are dropped (logged); nodes with
  coverage < 0.2 are flagged inactive but KEPT (the paper's cluster c2 —
  persistent-nulls nodes — is an important finding; NaNs are filled with 0 only
  at the DR input step, with an `inactive` flag carried to the UI).
- Constant metrics (std == 0) are dropped before DR (PCA/ccPCA degenerate).

tests: synthetic tensor round-trip; null-segment detection against injected gaps;
grid alignment property tests (hypothesis).

milestone: `get_tensor()` returns a correct bundle for 500 nodes × 100 metrics ×
1 day @15 s (T=5760) in < 30 s cold, < 1 s cached.

---

## PHASE 3 — INTER-CLUSTER ANALYSIS (MulTiDR + k-means + ccPCA)

goal: Reproduce the paper's inter-cluster pipeline exactly, with the paper's
defaults, as pure functions in analysis-core.

package: analysis-core/analysis_core/inter/

### 3.1 Two-phase DR (MulTiDR)

```
inter/multidr.py
```

```python
def dr1_pca_over_time(X: np.ndarray) -> np.ndarray:
    """X: (N, M, T) -> V: (N, M).
    For each metric m: fit PCA(n_components=1) on the (N, T) slice X[:, m, :]
    (rows = nodes, features = timesteps); V[:, m] = first PC scores.
    Standardize each slice over T before fitting. NaN -> 0 after standardization.
    This compresses each node's temporal pattern per metric into one
    'temporal variation' value, preserving fine-grained temporal patterns
    (paper Sec III-B-1)."""

def dr2_umap(V: np.ndarray, n_neighbors: int = 15, min_dist: float = 0.1,
             random_state: int = 42) -> np.ndarray:
    """V: (N, M) -> E: (N, 2). Paper defaults: n_neighbors=15, min_dist=0.1
    (Ganglia); the Theta case used n_neighbors=50, min_dist=0.5 — both must be
    settable from the UI."""
```

### 3.2 Clustering

```
inter/clustering.py
```

- k-means on E (N,2); default k=4; k user-configurable 2–12; `random_state=42`,
  `n_init=10`. Return labels + centroids.
- Provide `recluster(E, k)` as a separate cheap call (operates on cached E).

### 3.3 Cluster explanation (ccPCA) — replaces v1's deep-learning Phase 4

```
inter/ccpca.py
```

Input: the FIRST-PASS result V (N, M) partitioned by cluster labels (paper:
"we partition the first-pass DR result based on the cluster labels").
One-vs-rest: for each cluster c, target = V[labels==c], background = V[labels!=c].

Implementation options (in order of preference):
1. Use the author-published `ccpca` package (github.com/takanori-fujiwara/ccpca)
   if it installs cleanly (C++ extension; verify in CI).
2. Otherwise implement contrastive PCA directly (~80 lines):
   `C = cov(target) - alpha * cov(background)`; top eigenvector = weight vector.
   Automatic alpha: line-search over log-spaced alphas in [1e-2, 1e2], pick the
   alpha maximizing discrepancy between target/background projections
   (ccPCA paper's best-alpha strategy; document the chosen criterion).

Output per cluster: `weights: (M,)` — magnitude = metric importance to cluster
uniqueness; sign = direction of variation. Also return metrics ranked by |w|.

### 3.4 Stage cache (the paper's key performance mechanism)

```
inter/pipeline.py
```

```python
class InterClusterPipeline:
    """Stages: tensor -> V (dr1) -> E (dr2) -> labels (kmeans) -> ccpca weights.
    Each stage cached under key = hash(upstream_key + stage_params).
    Changing k re-runs ONLY kmeans + ccpca (target < 100 ms for N<=2000).
    Changing UMAP params re-runs dr2 onward. Changing time range invalidates all."""
```

Cache backend: in-process LRU + Redis (Phase 5) with numpy-npz values.

### 3.5 Cluster quality metrics (used in Phase 7 and exposed in the API)

```
inter/quality.py
```
silhouette, Davies–Bouldin, Calinski–Harabasz on (E, labels); trustworthiness &
continuity between V and E (sklearn.manifold.trustworthiness; implement
continuity as trustworthiness with roles swapped).

tests:
- Synthetic tensor with 4 planted behavioral groups (distinct temporal patterns
  per group) -> pipeline recovers 4 clusters with ARI > 0.9.
- ccPCA on planted data ranks the discriminative metric first for each cluster.
- Cache: second run of recluster() is >100× faster than cold pipeline.

milestone: CLI `python -m analysis_core.inter.run --start ... --end ...
--resolution 60 --k 4` prints cluster sizes, quality metrics, and top-5
discriminative metrics per cluster.

---

## PHASE 4 — INTRA-CLUSTER ANALYSIS (mrDMD + baselines + z-scores)

goal: Reproduce the paper's intra-cluster workflow on RAW time series.

package: analysis-core/analysis_core/intra/

### 4.1 mrDMD with frequency isolation

```
intra/mrdmd.py
```

- Use `pydmd.MrDMD` (wrap `pydmd.DMD(svd_rank=-1)`), `max_level` chosen so the
  finest level window >= 32 timesteps; `max_cycles=1` default, configurable.
- Input: cluster sub-tensor for ONE metric at a time: S (n_nodes, T) — the paper
  computes per-metric mrDMD (z-score heatmap is metric × node).
- `mrdmd_spectrum(S) -> list[Mode]` where Mode = {level, window, omega (freq),
  amplitude: (n_nodes,), power}.
- `isolate_band(modes, f_low, f_high)`: keep modes with |Im(omega)|/(2π) in the
  band. Provide named bands mapped from timestep resolution:
  5m, 30m, 2h, 24h, 7d (band edges computed from resolution_s; document formula).
- Handle NaNs: interpolate gaps <= 3 steps; longer gaps split the series and
  mrDMD runs on the longest contiguous segment (record which segment was used —
  the UI must show it).

### 4.2 Baseline extraction (paper Sec III-B-2, verbatim algorithm)

```
intra/baseline.py
```

```python
def default_baseline(S: np.ndarray) -> tuple[slice, np.ndarray]:
    """1) Compute IQR (Q1, Q3) of ALL measurements across selected nodes.
       2) Find the LONGEST contiguous time window where ALL values (every node)
          lie within [Q1, Q3].
       3) Tile (duplicate) that window across the full series length to
          simulate 'normal' behavior -> B (n_nodes, T).
       Return the window slice (for UI display/adjustment) and B."""

def user_baseline(S, t0: int, t1: int) -> np.ndarray:
    """Tile a user-brushed window [t0, t1) instead. Baselines are per-metric
    and user-adjustable (paper Fig. 3) — this function backs that interaction."""
```

### 4.3 Z-scores

```
intra/zscores.py
```

- Compute mrDMD modes for S and for B with identical parameters and band.
- For each node n and metric m: z[n, m] = (a_S[n] - mean(a_B)) / std(a_B),
  where a_* are band-aggregated mode amplitudes (sum of |amplitude| of retained
  modes). Guard std==0 -> z=0 with a flag.
- Output `ZResult {z: (n_nodes, n_metrics), baseline_windows: dict[metric, slice],
  band, segment_used}`.

### 4.4 Caching
Same content-addressed scheme as Phase 3: key = hash(cluster_node_set, metric,
time_range, band, baseline_window). Adjusting the baseline re-runs ONLY 4.2–4.3
for that metric (target < 500 ms for 100 nodes × 5,000 timesteps).

tests:
- Synthetic: 20 nodes with a shared sinusoid + 2 nodes with an injected
  amplitude/frequency anomaly -> those 2 nodes get |z| > 3 in the right band.
- Baseline finder: on a series with a known quiet interval, returns that interval.
- Frequency isolation: a 2 h oscillation appears only in the 2 h band.

milestone: CLI produces the metric×node z-score matrix for a chosen cluster and
band; anomalous synthetic nodes are correctly flagged.

---

## PHASE 5 — ANALYSIS API + CACHE SERVICE

goal: Expose the pipelines behind a low-latency API matching the UI's
interaction loop.

repo: analysis-api/  stack: FastAPI + Redis + tensor-store + analysis-core

endpoints (all POST, pydantic-typed; every response includes `cache_key` and
`timings_ms` per stage so the UI can display recompute cost):

```
/session/create        {tensor_request} -> {session_id}   # materializes tensor, warms dr1
/inter/embedding       {session_id, umap_params} -> {E, inactive_flags}
/inter/clusters        {session_id, k} -> {labels, centroids, quality_metrics}
/inter/explain         {session_id, k} -> {per-cluster ccPCA weights, ranked metrics}
/inter/timedomain      {session_id} -> {null_segments per cluster}      # Time Domain view
/inter/cluster_means   {session_id, metrics, smoothing_w} -> polylines  # Metric Reading 3b
/intra/zscores         {session_id, node_ids, metrics, band, baseline?} -> ZResult
/intra/baseline        {session_id, metric, node_ids} -> {default window, IQR}
/raw/series            {session_id, node_ids, metrics, t0, t1} -> downsampled raw readings
/jobs/overlay          {session_id, node_ids} -> job intervals (from ClickHouse jobs)
```

Rules:
- Enforce the analysis envelope (N ≤ 2000, M ≤ 500, T ≤ 10000) with 422 errors.
- Redis stores stage artifacts (npz bytes) keyed by content hash; TTL 24 h.
- Latency targets (paper-derived): warm recluster/explain < 200 ms; baseline
  adjust + z-score refresh < 500 ms; cold session create allowed up to 60 s
  with async status polling (`/session/{id}/status`).

tests: httpx integration tests against a synthetic ClickHouse fixture (or a
parquet-backed test loader in tensor-store); latency assertions on warm paths.

milestone: full inter+intra loop drivable via curl; warm-path latencies met.

---

## PHASE 6 — UI: FOUR COORDINATED VIEWS

goal: Reproduce the paper's interface (Fig. 2) and interactions (Fig. 3).
Read /mnt/skills/public/frontend-design/SKILL.md before scaffolding.

repo: behavior-ui/  stack: React + TypeScript + Vite; D3 for all four views
(DeckGL unnecessary at N ≤ 2000 points — drop it); Zustand for cross-view state;
MUI for controls.

Cross-view state (single store):
```
{ session, timeWindow, umapParams, k, selectedClusterIds, lassoNodeIds,
  selectedMetrics, band, baselines: {metric -> [t0,t1]}, hoveredCell }
```

### View 1 — Time Domain view
Stacked bar chart of null-reading segments per cluster over time (one row per
cluster, bars where nodes had all-metric nulls; distinguish planned downtime if
all clusters go null simultaneously). Brushing sets `timeWindow`, which filters
the Metric Reading raw plots (paper Fig. 2-1 -> 2-3c).

### View 2 — Node Similarity view
UMAP scatter (E), points colored by k-means cluster. Right-hand panel:
n_neighbors, min_dist numeric inputs; k selector; "Recompute" and
"Reset Defaults" buttons (paper Fig. 2-2). Lasso selection -> `lassoNodeIds`
drives Metric Reading comparison and intra-cluster node columns. Inactive nodes
(coverage flag) rendered hollow.

### View 3 — Metric Reading view (three components)
3a metric selection panel: searchable/filterable metric list; each metric shows
   a horizontal diverging bar chart of ccPCA contribution per cluster
   (length=|weight|, direction: left=higher, right=lower); metrics ranked by
   max |contribution|.
3b cluster reading summary: per-cluster average polylines over time for selected
   metrics, with a smoothing-window control.
3c reading inspection: raw time series for lasso-selected nodes; BRUSH over the
   chart to set the per-metric baseline window (`baselines[metric]`), with the
   statistically-derived default region pre-shaded (paper Figs. 2-3c, 3-2).

### View 4 — Node Behavior view
Heatmap: rows = selected metrics, columns = selected nodes, cells = mrDMD
z-scores (diverging color scale, fixed domain e.g. [-5, 5]). Recomputes when
band or any baseline changes. Hovering a cell highlights the corresponding raw
series in 3c (paper Fig. 2-4). Column labels colored by cluster.

Also implement the job overlay used in the case studies: toggle to shade job
intervals on 3c and annotate nodes "not mapped to any jobs".

acceptance (scripted E2E with Playwright against synthetic data):
- Change k from 4 to 5 -> scatter recolors in < 1 s without recomputing UMAP.
- Lasso a sub-group -> 3c shows their raw series.
- Brush a new baseline on one metric -> only that metric's heatmap row updates.
- Brush Time Domain -> 3c time range updates.

milestone: an operator can replicate the paper's Ganglia workflow end-to-end:
spot a downtime event in View 1, isolate a sub-cluster in View 2, pick
high-contribution metrics in 3a, adjust a baseline in 3c, and read anomalous
nodes off View 4.

---

## PHASE 7 — VALIDATION & EVALUATION

goal: Make "meaningful clusters" falsifiable and replicate the paper's checks.

repo: evaluation/

1. Cluster quality benchmark: run the pipeline on (a) synthetic planted-cluster
   data, (b) a public HPC dataset if licensable (e.g., Ganglia-style exports), or
   (c) 1 week of the platform's own telemetry. Report silhouette,
   Davies–Bouldin, Calinski–Harabasz, trustworthiness, continuity — the paper's
   Table I metric set — into a markdown report artifact per run.
2. Fault-injection tests: scripted perturbations on synthetic nodes
   (CPU-steal, memory leak ramp, IB error bursts, dead node) -> assert the
   injected nodes surface in the top-decile |z| for the right metrics/bands.
3. Ground-truth cross-check: join detected anomalies against `jobs` and any
   operator logbook table; compute precision@k on known incidents.
4. DR ablation (paper Fig. 9): compare PCA-only, UMAP-direct, t-SNE against the
   default MulTiDR pipeline on the same labels; keep as a notebook +
   regenerable report.

gates: Phase 3 ships only if planted-cluster ARI > 0.9 and quality metrics beat
PCA-only baseline; Phase 4 ships only if injected anomalies are recovered with
recall ≥ 0.9 at |z| ≥ 3.

---

## PHASE 8 (OPTIONAL, EXPLICITLY BEYOND THE PAPER) — SCALE-OUT & STREAMING

Only start after Phases 1–7 are accepted. Items, in priority order:
1. Incremental refresh: rolling tensor windows; re-run dr1 only on new
   timesteps' slices; parametric UMAP or `umap.transform()` for new/updated
   nodes to keep coordinates stable between sessions; Procrustes-align
   successive embeddings; Hungarian-match k-means labels across refreshes so
   cluster identity/colors persist.
2. ClickHouse replication + Redpanda 3-node cluster + retention tiering to
   MinIO/S3 for raw data > 45 days.
3. Multi-user sessions and saved analyses (baselines, lassos, annotations
   persisted per user).
4. Alerting: scheduled headless runs of the intra pipeline on each cluster with
   last-known-good baselines; push |z| ≥ threshold events to `anomalies` table +
   webhook. Include false-positive feedback (operator dismiss -> suppress rule).
5. (Research track) Deep contrastive node embeddings as an ALTERNATIVE dr1 —
   evaluate against MulTiDR with Phase 7 metrics before any adoption. This is
   where v1's InfoNCE idea lives, gated behind evidence.

---

## FINAL DATA FLOW (corrected)

Compute nodes (node_exporter / DCGM / IB counters)
  -> OTel Collector -> Redpanda -> ClickHouse (raw + 1m rollups, jobs, inventory)
  -> tensor-store (N×M×T bundle + null segments, cached)
  -> INTER: PCA-over-time (V: N×M) -> UMAP (E: N×2) -> k-means -> ccPCA weights
  -> INTRA (user-selected cluster/metrics/window): mrDMD + frequency isolation
     -> IQR/user baseline -> z-scores
  -> FastAPI (+ Redis stage cache)
  -> React four-view UI (Time Domain | Node Similarity | Metric Reading | Node Behavior)

## SUCCESS CRITERIA (per phase, testable)

- P1: synthetic 200-node fleet visible in Grafana; null segments detectable by query.
- P2: tensor bundle correct on fixtures; cached retrieval < 1 s.
- P3: planted clusters recovered (ARI > 0.9); recluster warm path < 200 ms;
      ccPCA ranks planted discriminative metrics first.
- P4: injected temporal anomalies recovered (recall ≥ 0.9 at |z| ≥ 3);
      baseline adjust -> refresh < 500 ms.
- P5: full loop drivable over HTTP within latency targets.
- P6: Playwright E2E reproduces the paper's Ganglia-style workflow.
- P7: evaluation report generated automatically per release; gates enforced in CI.
