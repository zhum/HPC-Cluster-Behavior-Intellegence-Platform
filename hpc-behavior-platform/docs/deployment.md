# Deployment Options

## 1. Dev single-node stack

`ingest-infra/docker-compose.yml` — single-broker Redpanda, single-node ClickHouse, OTel Collector, Grafana (anonymous admin), Redis, optional `synth-loader` profile. This is the baseline every other environment builds on. See [Quick Start](./quick-start.md).

Not suitable for production: no replication, anonymous Grafana admin, plaintext dev credentials (`devpass`), TTL-based deletion only (no cold tier).

## 2. HA overlay

`ingest-infra/docker-compose.ha.yml` — standalone, opt-in overlay. Deliberately **not** merged into the dev compose file: separate network, volumes, service names, and ports (ClickHouse on 8124/8125, Redpanda on 9093) to avoid collisions if you run both side by side.

```bash
cd hpc-behavior-platform/ingest-infra
docker compose -f docker-compose.ha.yml up -d
./ha/verify.sh   # checks replication, Redpanda health/RF, tiering — ~40s
```

Contains:

- 3-node ClickHouse Keeper quorum
- 2 ClickHouse replicas (`ReplicatedMergeTree` / `ReplicatedReplacingMergeTree` / `ReplicatedAggregatingMergeTree` — schema in `ingest-infra/ha/clickhouse/schema_ha.sql`)
- 3-broker Redpanda cluster, topics at replication factor 3
- MinIO S3-compatible cold tier — ClickHouse storage policy (`ingest-infra/ha/clickhouse/common/storage.xml`) moves `metrics_raw` parts older than 45 days to `s3_cold` instead of deleting them

### Known rough edges (documented in `ingest-infra/ha/README.md`)

- Keeper healthcheck needs `four_letter_word_allow_list` enabled, and must target `127.0.0.1`, not `localhost`.
- `TTL ... TO DISK` needs an explicit `toDateTime()` wrap.
- `ReplicatedReplacingMergeTree` needs an explicit `replica_name` argument.
- No `ON CLUSTER` DDL is used, to avoid a startup-ordering race.

## 3. Real hardware / OCI GPU cluster

Bring-up steps: [runbook-raw-hardware.md](./runbook-raw-hardware.md) — hardware pre-reqs, two paths (existing scrapers vs fresh install on compute nodes).

Draft test plan: `docs/test-plan-hardware-oci.md` (not yet executed — sign-off table is blank). Covers two target environments:

- **Env A** — on-prem HPC hardware: real Slurm, real InfiniBand, real DCGM GPUs.
- **Env B** — OCI bare-metal GPU shapes (`BM.GPU.H100.8` / `BM.GPU.A100-v2.8`), OCI RDMA cluster network, OCI HPC Slurm images or self-managed Slurm.

### Integrating with an already-deployed monitoring stack (test plan §0.1)

Preferred path if `node_exporter` / `dcgm-exporter` are already running:

1. Reuse those endpoints read-only — point this platform's OTel Collector Prometheus receiver at them.
2. Deploy only the two custom pollers fresh: `ib_poller.py`, `slurm_poller.py` (`ingest-infra/tools/`). These are the only two custom collectors the spec permits.
3. Deploy the backend (Redpanda, ClickHouse, Redis, analysis-api) as new, parallel infra.
4. Watch for: port collisions with the existing stack, metric-name mismatches, and IB/RoCEv2 sysfs-path differences — OCI's RDMA counters may not sit at the standard `/sys/class/infiniband` path (open item, unresolved as of the last test-plan draft).

### Architectural constraint to carry into any deployment runbook

`SessionStore` in `analysis-api` is in-process (a plain dict, not Redis-backed). **Run a single uvicorn worker.** Multiple workers will silently break session visibility — a request handled by worker B won't see a session created on worker A. This is documented in `analysis_api/session.py` and repeated in the test plan (§5.2) precisely because it's easy to miss when someone reflexively scales workers for throughput.

### Sizing (from the v2 spec)

- `ingest_server`: 32 vCPU / 128 GB / 2 TB NVMe
- `storage_server`: 32 vCPU / 256 GB / 8 TB NVMe

### Retention math

Worst case ~333k points/s at 10k nodes × 500 metrics / 15s interval → ~115 GB/day → ~60 days retained on 7 TB usable. `metrics_raw` TTL is set to 45 days (conservative); `metrics_1m` rollups are retained 1 year. Documented in `ingest-infra/README.md` and the header comment of `ingest-infra/clickhouse/schema.sql`.

This is a config knob, not a fixed constant — re-measure against real data once it lands:

```sql
SELECT sum(bytes_on_disk) / sum(rows) FROM system.parts WHERE table = 'metrics_raw';
```

Called out again in the OCI test plan §2.6.

## Choosing an option

| Scenario | Use |
|---|---|
| Local dev, demo, laptop | Dev single-node stack |
| Staging, want to validate replication/failover behavior | HA overlay |
| Production against real HPC/OCI hardware | HA overlay + hardware test plan checklist, single-worker analysis-api |

None of these ship an auth layer. See [Admin Guide § Security posture](./admin-guide.md#security-posture) before exposing any of this beyond a trusted network.
