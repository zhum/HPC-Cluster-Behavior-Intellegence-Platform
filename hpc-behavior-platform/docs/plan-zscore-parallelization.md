# Plan: z-score parallelization + latency benchmark

Status: PLANNED (not implemented). Companion to `docs/test-plan-hardware-oci.md` —
the benchmark half of this plan is meant to run on the same real-hardware/OCI
environments.

## 1. Context

`compute_zscores` (`analysis-core/analysis_core/intra/zscores.py`) processes
selected metrics in a sequential Python loop. Per metric it runs:

1. `default_baseline` / `user_baseline` — cheap (percentile + linear scan + tile).
2. `mrdmd_spectrum(S)` and `mrdmd_spectrum(B)` — expensive: pydmd `MrDMD` fits
   one SVD-backed DMD per (level, window) node of the binary tree; Python-level
   overhead (tree walk, object churn) plus LAPACK SVDs.
3. `_band_amplitude` — cheap reduction.

The metrics are fully independent — no shared mutable state, no RNG anywhere in
the intra path — so the loop is embarrassingly parallel across metrics. This is
the interactive Node Behavior view path (`POST /intra/zscores` in
`analysis-api/analysis_api/routers/intra.py`), so latency directly shapes UX.
The Redis stage cache (`run_staged`) absorbs repeats of the *same* request, but
every new metric selection / baseline brush / band change is a cold compute.

Envelope bounds the worst case (`analysis-api/analysis_api/envelope.py`):
N ≤ 2000, M ≤ 500, T ≤ 10000. A typical interactive slice is far smaller:
one cluster (~50–500 nodes) × 4–30 selected metrics × one day at 1m (T=1440).

Why this was deferred during the review pass: the change sits on the
interactive API path, and process pools bring real costs (worker spawn, per-task
array shipping, BLAS thread oversubscription) that can make small workloads
*slower*. Adopt only on benchmark evidence.

## 2. Implementation design

### 2.1 API surface

Add an `n_jobs` parameter to `compute_zscores`, default `1` (== current serial
behavior, bit-for-bit):

```python
def compute_zscores(
    tensor_by_metric: dict[str, np.ndarray],
    band: str,
    resolution_s: float,
    baseline_windows: dict[str, tuple[int, int]] | None = None,
    max_cycles: int = 1,
    min_finest_window: int = MIN_FINEST_WINDOW,
    n_jobs: int = 1,
) -> ZResult:
```

Semantics: `1` = in-process serial loop (no joblib involvement at all, zero new
overhead on the default path); `>1` = that many workers; `-1` = all cores.

### 2.2 Worker function

Extract the loop body into a module-level pure function so it pickles cleanly
(no closures, no lambdas):

```python
class _MetricResult(NamedTuple):
    a_S: np.ndarray            # (n_nodes,) band amplitude, signal
    a_B: np.ndarray            # (n_nodes,) band amplitude, baseline
    window: tuple[int, int]    # baseline window used
    segment: tuple[int, int]   # segment mrDMD ran on


def _metric_band_amplitudes(
    S: np.ndarray,
    f_low: float,
    f_high: float,
    user_window: tuple[int, int] | None,
    max_cycles: int,
    min_finest_window: int,
) -> _MetricResult:
    if user_window is not None:
        window = slice(*user_window)
        B = user_baseline(S, *user_window)
    else:
        window, B = default_baseline(S)
    modes_S, seg_S = mrdmd_spectrum(S, max_cycles=max_cycles, min_finest_window=min_finest_window)
    modes_B, _ = mrdmd_spectrum(B, max_cycles=max_cycles, min_finest_window=min_finest_window)
    n_nodes = S.shape[0]
    return _MetricResult(
        a_S=_band_amplitude(n_nodes, modes_S, f_low, f_high),
        a_B=_band_amplitude(n_nodes, modes_B, f_low, f_high),
        window=(window.start, window.stop),
        segment=(seg_S.start, seg_S.stop),
    )
```

Key points:
- Slices (`slice` objects) converted to plain int tuples at the worker boundary
  (picklable, and `ZResult` reconstruction converts back). `ZResult` schema is
  unchanged — callers (`routers/intra.py`, `intra/run.py`, evaluation) untouched.
- Worker returns only small arrays (2 × n_nodes floats) + tuples: the expensive
  `Mode` lists never cross the process boundary.
- Payload *into* the worker is `S` (n_nodes × T float64). joblib/loky
  auto-memmaps arrays ≥ 1 MB, so repeated dispatch does not re-pickle large
  slices; still, this is the dominant IPC cost to measure.

The serial path (`n_jobs == 1`) calls `_metric_band_amplitudes` directly in the
loop; the parallel path is:

```python
from joblib import Parallel, delayed

results = Parallel(n_jobs=n_jobs, backend="loky", inner_max_num_threads=1)(
    delayed(_metric_band_amplitudes)(
        tensor_by_metric[m], f_low, f_high, (baseline_windows or {}).get(m),
        max_cycles, min_finest_window,
    )
    for m in metrics
)
```

`Parallel` preserves input order, so `z[:, m_i]`, `baseline_windows_used`,
`segment_used`, and `degenerate_metrics` come out in the same order as the
serial loop. z assembly (std guard, degenerate flagging) stays in the parent —
one place, unchanged semantics.

### 2.3 BLAS oversubscription

Each loky worker inherits the full OpenBLAS/MKL thread count; k workers × c BLAS
threads thrash. `inner_max_num_threads=1` (joblib ≥ 1.2, loky backend) pins
worker BLAS pools to 1 thread. The benchmark grid (§3) also measures the
alternative — few workers × multithreaded BLAS — because pydmd SVDs on wide
matrices sometimes profit more from BLAS threads than from process fan-out.

### 2.4 Backend choice

Benchmark decides between:
- `backend="loky"` (processes): sidesteps GIL fully; costs spawn (~1–2 s first
  call, pool then reused process-wide by joblib) + memmap/pickle per task.
- `prefer="threads"`: zero IPC, shared memory; helps only if LAPACK holds the
  GIL released long enough — pydmd's Python-level tree overhead does not.

Expectation: loky wins for M ≥ ~8 and T ≥ ~1000; threads may win for small
slices. Plan codes backend as a parameter of the benchmark, ships whichever
wins, keeps the other reachable via env var for ops experimentation.

### 2.5 API wiring

`routers/intra.py` passes `n_jobs` from a new setting (env var
`ANALYSIS_ZSCORE_N_JOBS`, default `1`), NOT from the request payload — a client
must not be able to fork 64 processes per request. Read it wherever the other
service settings live (follow the existing config pattern in
`analysis_api/deps.py`).

Interaction with FastAPI: the endpoint is sync-def (threadpool). Two concurrent
requests would share the joblib loky pool (joblib serializes access safely) —
acceptable; note it in the service README. Uvicorn multi-worker deployments get
one loky pool per API worker: cap `ANALYSIS_ZSCORE_N_JOBS × uvicorn workers ≤
physical cores` in deployment docs.

### 2.6 Dependency

`joblib` is already installed transitively via scikit-learn; add it as an
explicit dependency of `analysis-core` (`joblib>=1.3`) since it becomes a direct
import.

### 2.7 Tests (analysis-core/tests/test_zscores.py additions)

1. **Determinism/equivalence (the critical one):** for a synthetic
   `tensor_by_metric` (e.g. 8 metrics, 20 nodes, T=480, mixed default + user
   baselines, one degenerate metric), assert `n_jobs=2` output equals
   `n_jobs=1` output **exactly** (`np.array_equal`, not allclose — no RNG, no
   reduction reordering, so results must be bit-identical) across `z`,
   `baseline_windows`, `segment_used`, `degenerate_metrics`.
2. Order preservation: metric order in `ZResult.metrics` matches input dict
   order for `n_jobs>1`.
3. `n_jobs=-1` smoke test.
4. Empty metrics dict with `n_jobs>1` returns empty ZResult (no pool spawn).
5. Worker exception propagates (e.g. a metric with wrong shape raises in
   parent, not silently dropped).

GitNexus discipline: run `gitnexus_impact({target: "compute_zscores",
direction: "upstream"})` before the edit (was LOW risk at review time: direct
callers `intra/run.py:main`, `routers/intra.py`, evaluation) and
`gitnexus_detect_changes()` before committing.

## 3. Latency benchmark plan (real cluster)

### 3.1 Deliverables

- `evaluation/evaluation/zscore_latency.py` — benchmark runner, same style as
  the existing harness (writes `evaluation/reports/zscore_latency.md`; hook it
  into `run_all.py` behind a `--benchmarks` flag or keep standalone — it is too
  slow for the default report run).
- Report = markdown tables + the machine fingerprint (§3.5) so results from
  different hosts stay comparable.

### 3.2 What to measure

Two layers:

1. **Library layer** — `compute_zscores` wall time via `time.perf_counter`,
   the number the parallelization actually changes.
2. **Service layer** — `POST /intra/zscores` end-to-end via httpx against a
   locally launched analysis-api (staging cache MISS path forced by unique
   params per request; plus one warm-hit series to confirm the cache path is
   still the fast path and did not regress). Captures serialization
   (`z.tolist()` on a 2000-node × 500-metric matrix is itself nontrivial) and
   threadpool effects the library number hides.

Per configuration record: median + p95 of ≥ 5 repeats after 1 discarded warmup
(warmup absorbs loky pool spawn — report spawn cost separately as
`first_call_overhead_s`), peak RSS delta of the process tree (`psutil`
recursive children sum), and total CPU time / wall time (effective core
utilization).

### 3.3 Parameter grid

Synthetic input from `_phase_diverse_baseline`-style fixtures (deterministic,
seed=42), sized to bracket real usage:

| axis | values | rationale |
|---|---|---|
| n_nodes | 50, 200, 500, 2000 | small cluster → envelope max |
| M (metrics) | 4, 16, 64, 500 | typical selection → envelope max |
| T | 480, 1440, 10000 | 8h@1m, 1d@1m, envelope max |
| n_jobs | 1, 2, 4, 8, 16, -1 | 1 = serial baseline |
| backend | loky, threads | §2.4 decision |
| inner BLAS threads | 1, unlimited | §2.3 decision; toggle via `threadpool_limits` |
| max_cycles / min_finest_window | (1, 32), (8, 16) | default + impulse-detection settings |

Full cross-product is too big (~4600 cells); run three targeted sweeps:

1. **n_jobs sweep at the typical slice** (200 × 16 × 1440, defaults): the
   headline adoption number.
2. **Scaling sweep at best n_jobs from (1):** vary one of n_nodes/M/T at a
   time, others at typical — locates where parallelism stops paying (expected:
   M is the only axis that scales worker count utilization; n_nodes and T grow
   per-task cost and IPC payload).
3. **Backend/BLAS 2×2 at typical and at envelope-max slices.**

### 3.4 Metrics and decision rules

Adopt a default `ANALYSIS_ZSCORE_N_JOBS > 1` in deployment configs only if, on
the typical slice (sweep 1):

- speedup ≥ 1.5× median vs `n_jobs=1`, AND
- p95 does not regress at any grid point with M ≤ 16 (small selections must
  not pay pool overhead), AND
- peak RSS ≤ 2× serial, AND
- equivalence check (serial vs parallel output `np.array_equal`) passes at
  every grid point — the benchmark script asserts this on every run, so the
  benchmark doubles as a large-input correctness harness.

Otherwise ship `n_jobs` as opt-in (default 1) and record the measured
crossover point (the M above which parallel wins) in the report — the API
could later auto-select `n_jobs = min(cores, max(1, M // crossover_M))`;
leave that as a follow-up, do not build it speculatively.

Secondary check: with the winning config, one UI-facing target — cold
`/intra/zscores` p95 ≤ 2 s on the typical slice (matches the interactive
budget the Playwright acceptance tests use for view updates; adjust if the
spec pins a different number).

### 3.5 Environment fingerprint (print into every report)

- hostname, CPU model, physical/logical cores, NUMA layout (`lscpu`)
- RAM, cgroup CPU/memory limits if containerized (affects loky sizing)
- Python version, numpy version + `numpy.show_config()` BLAS lib,
  pydmd/joblib/scikit-learn versions
- `OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` env at launch
- git commit of the platform

### 3.6 Real-cluster runs (per docs/test-plan-hardware-oci.md environments)

1. Dev VM (whatever runs analysis-api today) — baseline numbers.
2. OCI GPU-cluster CPU side (the analysis stack is CPU-only; the interest is
   the many-core Epyc/Xeon behavior: BLAS lib differences, NUMA effects at
   n_jobs=16+).
3. One run against *real* telemetry via tensor-store (one day, one production
   cluster's nodes, real metric list) instead of synthetic fixtures — real
   series have NaN gaps, so `prepare_series` cost and shortened segments enter
   the picture; synthetic fixtures underestimate this.

### 3.7 Risks / gotchas to watch in the benchmark

- **loky pool spawn on first request** after API start: 1–2 s latency spike.
  If adopted, pre-warm the pool at service startup (one dummy
  `Parallel(n_jobs=N)(delayed(int)(0) ...)` in the FastAPI lifespan hook).
- **Memory:** loky memmaps big inputs to /dev/shm (or $JOBLIB_TEMP_FOLDER) —
  containers with small /dev/shm silently fall back to slower disk temp;
  fingerprint should record /dev/shm size.
- **Oversubscription with uvicorn workers** (§2.5) — benchmark single-worker
  API only; document the multiplication rule for ops.
- **Thread backend + pydmd:** if pydmd internals turn out not thread-safe
  (shared module state), threads backend results will be wrong, not just
  slow — the per-run equivalence assert catches this; if it fires, drop the
  threads arm entirely.
- **Fork-safety:** loky uses spawn, safe with BLAS/OpenMP. Never switch to
  `backend="multiprocessing"` (fork) inside the API process.
