# Admin Guide

## Security posture — read this before deploying anywhere non-trivial

**There is no authentication or authorization anywhere in this stack as shipped.**

- `analysis-api` has no login, no API keys, no RBAC. The `user_id` parameter on `/analyses*` endpoints (saved analyses) is a plain caller-supplied string with zero verification — ownership is enforced only by `WHERE user_id = ...` in ClickHouse queries (`analysis-api/analysis_api/saved_analyses.py`). Any caller can read/write any other user's saved analyses simply by supplying their `user_id`.
- Grafana runs with anonymous admin access in the dev compose stack (`GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`).
- ClickHouse dev credentials are hardcoded plaintext: user `default` / password `devpass`, with `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1`.
- MinIO (HA overlay cold tier) ships with `minioadmin`/`minioadmin`.
- No secrets manager or vault integration anywhere — everything is plaintext env vars or compose defaults.

None of this is a hidden bug — it's an explicit gap in the current implementation. Before exposing this stack beyond a trusted, network-isolated environment: put it behind your own auth proxy/gateway, rotate all default credentials, and disable Grafana anonymous access.

## Configuration

### `analysis-api` env vars (`analysis_api/main.py`)

| Var | Default | Purpose |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origin(s) |
| `REDIS_HOST` | `localhost` | Stage-result cache |
| `REDIS_PORT` | `6380` | (non-standard — 6379 avoided due to local port collisions) |
| `CLICKHOUSE_HOST` | `localhost` | |
| `CLICKHOUSE_PORT` | `8123` | |
| `CLICKHOUSE_PASSWORD` | `devpass` | **rotate before production** |

CLI tools (`analysis_core.inter.run`, `analysis_core.intra.run`, `alerting.run`) take the equivalent as flags: `--clickhouse-host/--clickhouse-port/--clickhouse-password`, same dev defaults baked in.

### Frontend

`behavior-ui/.env` (copy from `.env.example`): `VITE_API_BASE=http://localhost:8010`.

### Schema

Canonical schema: `ingest-infra/clickhouse/schema.sql` — `metrics_raw`, `metrics_1m` rollup materialized view, `jobs`, `node_inventory`, `anomalies`, `suppression_rules`, `baseline_state`, `saved_analyses`.

HA variant: `ingest-infra/ha/clickhouse/schema_ha.sql`, plus `storage.xml` (tiering policy), `cluster.xml`, per-node `macros.xml`.

## Deployment worker constraint

`SessionStore` in `analysis-api` (`analysis_api/session.py`) is **in-process**, not Redis-backed. Run a single uvicorn worker. Scaling to multiple workers breaks session visibility silently — a session created on one worker won't be seen by requests routed to another. Documented again in `docs/test-plan-hardware-oci.md` §5.2. If you need more throughput, scale via a load balancer in front of multiple single-worker instances with sticky sessions, or fix `SessionStore` to be Redis-backed first — don't just bump `--workers`.

## Request size limits

`analysis_api/envelope.py` hard-enforces N ≤ 2000 nodes, M ≤ 500 metrics, T ≤ 10000 timesteps, rejecting oversized requests with HTTP 422 instead of accepting slow/unbounded work. Set user expectations accordingly when sizing sessions for large clusters — a 10k-node cluster needs to be queried in node/metric/time slices, not as one session.

## Retention tiering

- Dev stack: `metrics_raw` TTL 45 days, then deleted. `metrics_1m` rollups retained 1 year.
- HA overlay: `metrics_raw` parts older than 45 days move to MinIO/S3 cold storage (`TTL ... TO DISK 's3_cold'`) instead of being deleted.

Retention math (worst case ~333k points/s at 10k nodes × 500 metrics / 15s interval → ~115 GB/day → ~60 days on 7 TB usable, hence the 45-day TTL) is documented in `ingest-infra/README.md` and the header comment of `ingest-infra/clickhouse/schema.sql`. Treat it as a starting estimate, not measured fact — re-check against real bytes/row once real data lands:

```sql
SELECT sum(bytes_on_disk) / sum(rows) FROM system.parts WHERE table = 'metrics_raw';
```

## Multi-user sessions and saved analyses

Saved analyses (baselines, lasso selections, metrics, band, k, UMAP params — full UI state as opaque JSON) persist per `user_id` in `saved_analyses`, a `ReplacingMergeTree(updated_at)` table with soft-delete (a `deleted` flag plus `FINAL` reads). Soft-delete was chosen over `ALTER TABLE ... DELETE` because that mutation isn't synchronously visible in ClickHouse — confirmed via live testing, per the code comment in `saved_analyses.py`. Don't "simplify" this to a hard delete without re-verifying that constraint.

Reminder: `user_id` is unauthenticated (see Security posture above) — this is a convenience namespace, not access control.

## HA infra

See [Deployment Options § HA overlay](./deployment.md#2-ha-overlay) for setup. Operationally:

- Verify health after bringing it up: `ingest-infra/ha/verify.sh` (~40s — checks ClickHouse replication, Redpanda health/replication factor, and tiering).
- Keeper healthcheck must target `127.0.0.1`, not `localhost`, and needs `four_letter_word_allow_list` enabled — a common misconfiguration if you're porting settings from a non-HA ClickHouse config.
- No `ON CLUSTER` DDL is used deliberately, to avoid a startup-ordering race — don't introduce it without re-testing cold-start behavior.

## Alerting

`alerting/` runs scheduled headless anomaly scans:

```bash
python -m alerting.run --lookback-s 3600 --resolution 60 --k 4 --band 2h \
  --webhook-url <url> --interval-s 300
```

`--interval-s 0` runs once and exits; `>0` loops.

Behavior:

- Compares current z-scores against last-known-good baselines (`baseline_state` table). The baseline is only updated after a *clean* run, so it never drifts to incorporate an ongoing, unresolved anomaly.
- New anomalies are written to the `anomalies` table and pushed to a webhook on a best-effort basis — a failed webhook delivery never drops the persisted anomaly row, so nothing is silently lost if the webhook endpoint is briefly down.
- Operator "dismiss" actions create a `suppression_rules` row, suppressing future alerts for that specific (node, metric, band) combination. There's no UI for this yet (see [User Guide](./user-guide.md)) — handle dismissals via direct table access or a script until one exists.

**Known caching bug already fixed, don't reintroduce it:** `tensor_store.get_tensor`'s disk cache keys only on request params, not on the underlying data — this caused stale bundles across repeated polling. `alerting` calls `get_tensor(..., use_cache=False)` specifically to avoid it. If you're adding another scheduled/polling consumer of `tensor_store`, do the same. See `alerting/README.md` § "A real bug this caught."

## Research track: deep contrastive embeddings

Phase 8 evaluated an InfoNCE-based deep contrastive embedding as an alternative to MulTiDR's first DR stage. Result: ARI 0.911 / silhouette 0.539, vs MulTiDR's 1.000 / 0.921.

**Verdict: do not adopt.** It's not wired into the production pipeline and is gated behind the `research` pip extra (`torch`) precisely so it never becomes a default dependency. If someone proposes enabling it in production, point them at `evaluation/README.md` and `evaluation/evaluation/research_contrastive.py` for the comparison — the classical pipeline measurably wins on this task.

## Monitoring the platform itself

Grafana (bundled in `ingest-infra`) is for *cluster telemetry* dashboards, not platform observability — there's no APM/tracing setup for `analysis-api`/`alerting` themselves in this repo. If you need to know whether the platform is healthy, use ClickHouse's `system.parts`/`system.replicas` (HA) and the `alerting`/`analysis-api` process logs directly; nothing is currently wired into Grafana for that purpose.
