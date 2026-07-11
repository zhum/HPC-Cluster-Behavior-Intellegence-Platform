# Test Plan: Real HPC Hardware Cluster + OCI GPU Cluster

Status: draft. Scope: validate Phases 1–8 (this repo) against real telemetry
sources instead of the synthetic `synth_nodes.py` loader used throughout
development. Two target environments, run independently:

- **Environment A — on-prem HPC hardware cluster**: physical nodes, real
  Slurm, real InfiniBand fabric, real DCGM-capable GPUs (if present).
- **Environment B — OCI GPU cluster**: OCI bare-metal GPU shapes
  (`BM.GPU.H100.8` / `BM.GPU.A100-v2.8` / similar), OCI's RDMA cluster
  network, either OCI HPC's own Slurm images or a self-managed Slurm
  control plane.

Everything below assumes Phases 1–8 are otherwise unchanged; findings that
require code changes get filed as follow-ups, not fixed inline during
testing.

---

## 0. Pre-requisites

| Item | Environment A | Environment B |
|---|---|---|
| Node count for initial pass | 8–20 physical nodes (enough to exercise clustering with >1 real group) | Start with 1 GPU node pool (2–8 nodes), scale to full shape count only after Phase 1–5 pass |
| Admin access | root/sudo on nodes for exporter install; Slurm admin for `slurmrestd` | OCI IAM policy for compute/network read; root on instances via cloud-init or bastion |
| Network | Access to a ClickHouse/Redpanda/Redis host reachable from all nodes (or run ingest stack on a dedicated node in-cluster) | Same, but confirm OCI security list / NSG allows ports 8123, 9092, 6379 between the ingest host and compute nodes |
| Telemetry sources | `node_exporter`, `dcgm-exporter` (if GPUs present), IB counters at `/sys/class/infiniband/*/ports/*/counters/*` | `node_exporter`, `dcgm-exporter` (GPU shapes have NVIDIA GPUs by definition); **confirm RDMA counter path** — OCI GPU cluster networking is RoCEv2, not always exposed at the same `/sys/class/infiniband` path as true IB; may need `ib_poller.py` path adjustment or `rdma-core` tooling substitution (open item, see Phase 1 test cases) |
| Job source | Real Slurm (`slurmrestd`) | Real Slurm if self-managed on OCI HPC images; if using a different scheduler, `slurm_poller.py` needs a source-specific rewrite (out of scope for this pass — note as a gap, don't block on it) |
| Chrony/NTP | Required (tensor builder aligns to a 15s grid; document actual skew observed) | OCI images ship NTP via `chronyd` to Oracle's NTP servers by default — verify enabled, don't assume |

---

## 0.1 Integrating with an already-deployed cluster (existing collectors present)

If the target cluster already runs its own monitoring (existing
`node_exporter`/`dcgm-exporter`, an existing Prometheus/Grafana stack),
**do not deploy duplicate node-level collectors** — `node_exporter` and
`dcgm-exporter` are stateless Prometheus-exposition endpoints; multiple
independent scrapers can pull from the same endpoint with zero conflict.
The rest of this platform's ingest path (OTel Collector → Redpanda →
ClickHouse → Redis → analysis-api) is net-new either way, since it's
specific to this project's schema and analysis — it sits *alongside*
existing monitoring, it doesn't replace it.

| # | Step | Notes |
|---|---|---|
| 0.1.1 | Inventory existing endpoints | Confirm `node_exporter:9100` / `dcgm-exporter:9400` (or whatever ports they're actually bound to) are reachable from wherever this platform's OTel Collector will run — same subnet, no firewall/NSG block |
| 0.1.2 | Point our OTel Collector at existing exporters | Edit `otel-collector-config.yaml`'s Prometheus receiver `scrape_configs` to target the existing exporter addresses directly. No new node-side agent install required for CPU/mem/GPU metrics |
| 0.1.3 | Deploy this platform's custom pollers in parallel | `ib_poller.py` and `slurm_poller.py` are the only two collectors this project owns (per the v2 spec, the *only* custom collectors permitted) — existing monitoring almost certainly doesn't expose these in this platform's schema/format, so deploy them fresh as lightweight systemd units (`telemetry-agent/configs/`) next to whatever's already running |
| 0.1.4 | Deploy this platform's backend stack fresh | Redpanda + ClickHouse + Redis + analysis-api are net-new services; they don't replace an existing Prometheus/Grafana. Check for port collisions on the target host before deploying — hit this exact issue in dev (6379 already bound by an unrelated service, remapped Redis to 6380) |
| 0.1.5 | Normalize metric names | Confirm the Prometheus metric names surfaced by the existing exporters match what `schema.sql`/tensor-store expect (`cpu.utilization`-style naming). If the existing deployment's relabeling differs, add an OTel Collector processor to remap on OUR side — don't touch the source exporters' config, which other consumers depend on |
| 0.1.6 | Canary rollout | Point the collector at a small node subset first, verify `metrics_raw` populates correctly and null-segment detection behaves as expected, before scraping the full fleet |
| 0.1.7 | If direct double-scraping is against policy | Some security-conscious environments restrict how many things can hit host-metrics endpoints directly. Alternative: receive via the *existing* Prometheus's remote-write or federation endpoint instead of a second direct scrape — this adds a dependency on their pipeline's retention/availability, so treat it as a fallback, not the default. Direct scrape (0.1.2) is the recommended path when allowed |

**Bottom line:** reuse existing node-level exporters as-is (read-only,
pull-based, no risk of conflict); deploy this platform's own ingest
backend and custom pollers as new, parallel infrastructure rather than
trying to graft this project's schema onto an existing pipeline.

---

## 1. Phase 1 (Telemetry Foundation) — real fleet

**Goal:** the same acceptance criteria as the synthetic-loader validation,
but against real exporters and real node counts.

| # | Test | Pass criteria |
|---|---|---|
| 1.1 | Deploy `node_exporter` + `dcgm-exporter` (if GPUs present) via the systemd units in `telemetry-agent/configs/`, point OTel Collector's Prometheus receiver at real scrape targets | `metrics_raw` shows nonzero row counts within 1 scrape interval per node |
| 1.2 | IB/RDMA counters — Env A (true IB) | `ib_poller.py` reads `/sys/class/infiniband/*/ports/*/counters/*` without modification |
| 1.3 | IB/RDMA counters — Env B (RoCEv2) | **Expected finding, not a blocker:** confirm whether OCI GPU shapes expose an equivalent sysfs path. If not, document the actual path/tooling (e.g., `mlx5` RoCE counters via `ethtool -S` or OCI's own network metrics) as a follow-up item for `ib_poller.py`; do not silently skip IB-class anomalies in later phases without noting this gap |
| 1.4 | Slurm ingestion | `jobs` table populates from `slurmrestd` polling; verify `node_list` matches actual allocated nodes for a real job |
| 1.5 | Clock sync | Query `max(ts) - min(ts)` across nodes for the same wall-clock scrape tick; must be sub-second per the 15s-grid assumption. **If not**, this directly threatens tensor-store's grid alignment (Phase 2) — escalate before proceeding |
| 1.6 | Retention math, real scale | Recompute the retention math comment in `schema.sql` using the REAL node/metric count × real scrape interval; confirm the 45-day TTL is still appropriate (don't just trust the comment — it was written for the paper's assumed worst case, not this cluster's actual shape) |
| 1.7 | Null-segment detection, real fault | Reboot or cordon one real node during a run; confirm a null segment appears in `metrics_1m`/`nulls.py` output at the correct timestamp, not just in the synthetic kill-test |

**Exit criteria:** 1.1, 1.2/1.3 (with 1.3's gap explicitly documented if real),
1.4, 1.5, 1.7 pass. 1.6 recomputed and TTL adjusted if needed.

---

## 2. Phase 2 (Tensor Store) — real-scale performance

**Goal:** re-validate the cold/warm latency milestone against this
cluster's REAL node×metric×T shape, not the synthetic 500×100×5760 target.
The synthetic benchmark was worst-case; the real number may be smaller or
larger.

| # | Test | Pass criteria |
|---|---|---|
| 2.1 | Compute this cluster's actual (N, M, T) for a 1-day-@-native-resolution window | Record the real numbers — this determines whether the existing <30s/<1s targets are even the right ones to hold this cluster to |
| 2.2 | Cold `get_tensor()` at real scale | Time it. If it exceeds the milestone, don't just accept it — check whether the gap is explained by known factors already documented in `tensor-store/README`/commit history (batching, SQL pushdown, numpy-scatter fast path) actually being exercised, or whether real data has a different bottleneck (e.g., many more metrics with low coverage triggering the coverage-filter path, which wasn't heavily benchmarked) |
| 2.3 | Warm (cached) `get_tensor()` | <1s per the milestone; if not, check whether `use_cache=True` is actually in effect for this call path (recall: `alerting`'s scheduler deliberately disables caching — make sure whichever caller you're testing here isn't accidentally doing the same) |
| 2.4 | Real null-segment coverage filtering | Confirm `METRIC_COVERAGE_MIN`/`NODE_COVERAGE_MIN` thresholds (0.5/0.2) are sensible for this cluster's actual telemetry reliability — a flakier real fleet may need these tuned, and that's a legitimate per-deployment config, not a bug |
| 2.5 | DateTime64 param bug regression check | This was a real clickhouse-connect bug found in dev (bare `datetime` silently matches 0 rows). Confirm it doesn't resurface with a different clickhouse-connect version pinned in this environment |

**Exit criteria:** real (N,M,T) recorded; cold/warm times recorded even if
they don't hit the synthetic milestone (the milestone was calibrated to a
hypothetical worst case, not this specific cluster — record actual numbers
and decide whether to retune targets, don't force-fit).

---

## 3. Phase 3 (Inter-Cluster Analysis) — real cluster structure

**Goal:** confirm MulTiDR/k-means/ccPCA produce sensible, stable output on
real telemetry, where "ground truth" clusters aren't known in advance
(unlike the synthetic planted-cluster fixture).

| # | Test | Pass criteria |
|---|---|---|
| 3.1 | Run the full inter pipeline on a real 1-day window | No crashes; quality metrics (silhouette, DB, CH) computed and in sane ranges — don't expect ARI>0.9 here, there's no ground truth |
| 3.2 | Manual plausibility check | For k=4-ish, do the resulting clusters correspond to something an operator recognizes (e.g., GPU nodes vs CPU-only nodes, or nodes in the same rack/partition)? This is a judgment call by whoever runs the test, not an automated assertion |
| 3.3 | ccPCA discriminative metrics | For each cluster, do the top-ranked metrics make physical sense (e.g., a GPU-heavy cluster ranking `dcgm.gpu_util` highly)? |
| 3.4 | Recluster warm-path latency | <200ms per the existing gate — this doesn't depend on cluster identity being "real", should hold regardless of node count within the analysis envelope |
| 3.5 | UMAP/dr1 stability across two back-to-back runs on the same window | Since `random_state=42` is fixed, results should be identical run-to-run. If not, something in the real data (e.g., NaN handling) is introducing nondeterminism — investigate before trusting any cluster output |

**Exit criteria:** 3.1, 3.4, 3.5 pass objectively. 3.2/3.3 are recorded as
qualitative findings for whoever owns interpreting the results (an SRE/HPC
operator familiar with this specific cluster's topology).

---

## 4. Phase 4 (Intra-Cluster Analysis) — real anomalies, not injected ones

**Goal:** the fault-injection tests (Phase 7's `evaluation/`) proved the
z-score pipeline against SYNTHETIC faults. This phase validates it against
whatever real incidents this cluster has actually had, or can safely be
made to have.

| # | Test | Pass criteria |
|---|---|---|
| 4.1 | Historical incident replay | If this cluster has logged incidents (a known bad GPU, a network flap) with a timestamp, run `compute_zscores` for that window/band and confirm the known-bad node(s) surface with high \|z\| | Recall/precision recorded, not gated at 0.9 — real incidents are messier than synthetic ones |
| 4.2 | Controlled fault injection, Env A only (if permitted) | With explicit authorization: a benign controlled stressor (e.g., `stress-ng --cpu` for a bounded window, or a deliberate short network interface flap) on ONE node; confirm it surfaces. **Do not run destructive fault injection on Env B (OCI) or shared/production infra without separate written authorization** — this is exactly the kind of action that needs sign-off beyond a test plan |
| 4.3 | Band/frequency sanity check on real periodic workloads | If this cluster runs anything with a known cadence (nightly batch jobs, periodic checkpointing), confirm the corresponding band picks up that periodicity — a real-world analog to the "2h period recovered by mrDMD" unit tests |
| 4.4 | Baseline adjust → refresh latency | <500ms per the existing gate |
| 4.5 | mrDMD known limitations, real-world check | The evaluation/ report documented that monotonic ramps (`memory_leak_ramp`) and short impulses (`ib_error_burst`) are NOT reliably caught by this pipeline. If Env A/B has a REAL slow memory leak or a REAL brief IB error burst on record, confirm whether real data behaves the same way (fails to surface) — this is valuable evidence either confirming or narrowing that documented limitation |

**Exit criteria:** 4.1 recall/precision recorded (even if imperfect — this
is the actual falsifiability check the paper's methodology calls for). 4.4
passes as a hard gate. 4.2 only with explicit written authorization.

---

## 5. Phase 5 (Analysis API) — load and latency at real scale

| # | Test | Pass criteria |
|---|---|---|
| 5.1 | Cold session create at real (N,M,T) | Record actual time; compare to the 60s allowance |
| 5.2 | Concurrent sessions | Multiple operators (or multiple test clients) creating sessions simultaneously — confirm no cross-session data leakage (the in-process `SessionStore` is per-process/per-worker; if this deploys behind >1 uvicorn worker, sessions won't be visible across workers — **this is a known architectural limitation documented in `analysis-api/analysis_api/session.py`, confirm the real deployment runs single-worker or accept this limitation explicitly** rather than discovering it as a surprise outage) |
| 5.3 | Redis stage cache under real load | Confirm cache hit rate is reasonable for a real multi-operator workload (repeated `/inter/clusters` calls with the same k should hit cache) |
| 5.4 | Envelope enforcement at real scale | If this cluster's real N/M/T exceeds the envelope (2000/500/10000), confirm the 422 fires cleanly rather than the request hanging or crashing |

**Exit criteria:** 5.1 recorded, 5.3/5.4 pass. 5.2's single-worker
constraint explicitly acknowledged in the deployment runbook if applicable.

---

## 6. Phase 6 (UI) — real operator workflow

**Goal:** replace the Playwright synthetic-data acceptance tests with a
manual (or lightly scripted) walkthrough using REAL cluster data, run by
someone who actually operates this cluster.

| # | Test | Pass criteria |
|---|---|---|
| 6.1 | End-to-end Ganglia-style workflow (per the Phase 6 milestone) using real data | An operator can: spot a real downtime event in View 1, isolate a real sub-cluster in View 2, find a plausible discriminative metric in 3a, adjust a baseline in 3c against a real quiet period, and read real anomalous nodes off View 4 |
| 6.2 | CORS / network | Confirm the UI's configured `VITE_API_BASE` and the API's `CORS_ORIGINS` are set for this environment's actual hostnames (both were hardcoded to `localhost` during dev) |
| 6.3 | Job overlay with real Slurm data | Toggle job overlay in 3c against real job intervals; confirm "not mapped to any jobs" annotation is meaningful (matches paper's Ganglia finding) rather than everything being unmapped due to a join-key mismatch |

**Exit criteria:** 6.1 signed off by an actual cluster operator (not just
an engineer who built the tool) — this is the test that most needs a real
human's judgment, not automation.

---

## 7. Phase 7 (Evaluation) — real dataset instead of synthetic

**Goal:** finally exercise the evaluation harness's option (c) — "1 week
of the platform's own telemetry" — which was explicitly NOT exercised
during development (no licensable public dataset, no week-long real
telemetry operated in that environment).

| # | Test | Pass criteria |
|---|---|---|
| 7.1 | Run `evaluation.quality_benchmark` against a real 1-week window | Report generated; Table I metrics recorded (no ARI available without ground truth — report silhouette/DB/CH only, and note in the report that ARI is N/A for this dataset) |
| 7.2 | Run `evaluation.dr_ablation` against the same window | Compare MulTiDR vs PCA-only/UMAP-direct/t-SNE on REAL data — the synthetic result (MulTiDR wins clearly) may not hold as strongly on real, messier telemetry; record honestly either way |
| 7.3 | Ground-truth cross-check | If this cluster has ANY operator logbook / incident tracker, run `ground_truth.precision_at_k` against it for real |

**Exit criteria:** all three produce a report artifact (even if some
numbers are "N/A" for lack of ground truth) — the point is establishing
this cluster's OWN baseline numbers, which future changes get compared
against, not re-litigating the synthetic gates already passed in Phase 7.

---

## 8. Phase 8 items — infra-specific

### 8.1 Incremental refresh (item 1)
Real test: run the dashboard against a live rolling window for several
hours; confirm cluster colors/identity stay visually stable across
refreshes (the actual point of Procrustes-alignment + Hungarian relabeling)
rather than just trusting the unit tests' synthetic two-node-add case.

### 8.2 HA infra + retention tiering (item 2)
- Env A: if this cluster has genuinely separate failure domains (racks,
  power zones), place the 2 ClickHouse replicas and 3 Keeper nodes across
  them for a REAL HA test — kill one replica mid-write, confirm no data
  loss and the other replica keeps serving.
- Env B (OCI): use separate OCI fault domains / availability domains for
  the same test — this is a meaningfully different (and more realistic)
  HA test than same-host docker-compose containers, since it exercises
  actual network partition behavior between fault domains.
- Retention tiering: confirm the target object storage is actually OCI
  Object Storage (S3-compatible) rather than MinIO for Env B, and that the
  storage policy's endpoint/credentials are updated accordingly — this is
  a real config change, not just pointing at a different host.
- Run `ingest-infra/ha/verify.sh` (already scripted) as the first pass
  before any manual fault-injection testing above.

### 8.3 Multi-user sessions (item 3)
Real test: 2+ actual operators using the platform concurrently against the
same cluster's data, confirming saved-analysis scoping holds for real
distinct identities, not just distinct test-generated UUIDs.

### 8.4 Alerting (item 4)
Real test: let the scheduler run unattended for several days against real
data; confirm webhook delivery actually reaches wherever it's configured
to (Slack/PagerDuty/etc — was only tested against a mock in dev), and that
a real operator dismissing a false positive actually suppresses it on the
next real run.

### 8.5 Research-track embeddings (item 5)
No new testing needed unless someone revisits the "DO NOT ADOPT" verdict
with a different architecture/training regimen — out of scope for this
pass.

---

## 9. Environment-specific risk notes

**Env A (on-prem hardware):**
- Physical access needed for any node-level fault injection (4.2) —
  coordinate with whoever else uses this cluster.
- Real IB fabric errors (if induced) can affect OTHER jobs sharing that
  fabric — confirm isolation before 4.2.

**Env B (OCI GPU cluster):**
- GPU-hour cost: OCI GPU shapes bill per hour regardless of utilization —
  scope the test window deliberately (this test plan doesn't need
  continuous multi-day GPU allocation for most sections; only 8.1's
  "several hours" and 8.4's "several days" genuinely need sustained
  compute, and 8.4 doesn't need GPUs at all, only the ingest+alerting
  stack running).
- RDMA/IB counter path (1.3) is the single biggest known unknown for this
  environment — resolve it early, since Phase 4's frequency-domain
  analysis on IB-class metrics depends on it.
- Confirm OCI network security rules (NSGs/security lists) allow the
  ingest stack's ports (8123 ClickHouse, 9092 Redpanda, 6379/6380 Redis,
  4317/4318 OTel) between compute nodes and the ingest host before
  debugging "no data" as an application bug — it's very often a network
  policy issue in cloud environments.

---

## 10. Sign-off

| Phase | Env A owner | Env B owner | Status |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 (operator walkthrough) | | | |
| 7 | | | |
| 8.1–8.5 | | | |

Fill in owners and status as each section runs; this table is the
executive summary for whoever needs a one-glance view of readiness.
