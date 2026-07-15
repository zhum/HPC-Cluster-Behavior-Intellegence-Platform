# Deployment Runbook: Raw Hardware Cluster

Scope: deploy this platform onto a real physical HPC cluster (Env A in
`test-plan-hardware-oci.md`). Two paths below, pick by current state of
target cluster's monitoring. Not for OCI GPU shapes — see test plan §0/§9
for OCI-specific notes (RDMA path, NSGs, GPU-hour cost).

---

## 0. Hardware pre-requisites

| Item | Spec | Notes |
|---|---|---|
| Compute nodes | any x86_64 Linux, kernel with `/sys/class/infiniband` if IB present | 8–20 nodes minimum for first pass — need enough for k>1 clustering to mean anything |
| GPUs (optional) | NVIDIA, DCGM-capable | skip `dcgm-exporter` install if no GPUs |
| `ingest_server` | 32 vCPU / 128 GB RAM / 2 TB NVMe | runs Redpanda, OTel Collector, analysis-api |
| `storage_server` | 32 vCPU / 256 GB RAM / 8 TB NVMe | runs ClickHouse (+ Keeper if HA) |
| Network | compute nodes ↔ ingest host reachable on 8123 (ClickHouse), 9092 (Redpanda), 6379/6380 (Redis), 4317/4318 (OTel gRPC/HTTP) | firewall/VLAN rules, not just routing — check both directions |
| Root/sudo | on every compute node, for exporter install | systemd unit install needs root |
| Slurm | `slurmrestd` reachable from wherever `slurm_poller.py` runs (can be the ingest host, polls centrally, not per-node) | `SLURMRESTD_TOKEN` — issue a read-scoped token, not admin |
| NTP | `chrony` or equivalent running on every node | tensor builder aligns to 15s grid; sub-second skew tolerated, more breaks Phase 2. Verify, don't assume |
| IB fabric (optional) | real InfiniBand, sysfs counters at `/sys/class/infiniband/*/ports/*/counters/*` | if RoCEv2 instead of true IB, path may differ — see test plan §1.3, treat as open item |

Before starting either option below, confirm network reachability both ways:

```bash
# from a compute node
nc -zv <ingest-host> 8123 9092 6379 4317 4318
```

---

## Option A — existing scrapers already running

Use when the cluster already runs its own `node_exporter` / `dcgm-exporter`
(possibly feeding an existing Prometheus/Grafana). **Do not install a second
copy on compute nodes** — both are stateless Prometheus-exposition
endpoints; this platform reads them read-only, no conflict, but no reason
to duplicate.

1. **Inventory existing endpoints.** Confirm `node_exporter:9100` and
   `dcgm-exporter:9400` (or whatever ports are actually bound) are reachable
   from the ingest host — same subnet/VLAN, no firewall block.

2. **Point this platform's OTel Collector at them.** Edit
   `ingest-infra/otel/otel-collector-config.yaml`'s `prometheus.scrape_configs`
   targets to the real node hostnames/IPs instead of the docker-compose
   service names (`node-exporter:9100`, `dcgm-exporter:9400`). One target
   entry per node, or a service-discovery block if the fleet is large.
   No new node-side agent required for CPU/mem/GPU metrics.

3. **Deploy the two custom pollers fresh** (these are the *only* two
   collectors this platform owns — nothing else running on the cluster
   will produce this schema):
   - `ib_poller.py` — one instance per IB-equipped node. Install as systemd
     unit from `telemetry-agent/configs/ib_poller.service`, set `NODE_ID`
     and `KAFKA_BROKERS=<ingest-host>:9092` per host.
   - `slurm_poller.py` — one instance, centrally (not per-node). Set
     `SLURMRESTD_URL` and `SLURMRESTD_TOKEN` env vars, `KAFKA_BROKERS`
     pointing at the ingest host.

   ```bash
   # on the node/host running each poller
   pip install -r ingest-infra/tools/requirements.txt
   NODE_ID=$(hostname) KAFKA_BROKERS=<ingest-host>:9092 \
     python3 ingest-infra/tools/ib_poller.py
   ```

4. **Deploy this platform's backend fresh** (Redpanda, ClickHouse, Redis,
   analysis-api) — net-new, doesn't replace the existing monitoring stack.
   Use the HA overlay (`docker-compose.ha.yml`) for anything beyond a demo;
   see [deployment.md §2](./deployment.md#2-ha-overlay).

   ```bash
   cd hpc-behavior-platform/ingest-infra
   docker compose -f docker-compose.ha.yml up -d
   ./ha/verify.sh
   ```

   Check for port collisions on the ingest host before starting — hit this
   in dev (6379 already bound, remapped Redis to 6380).

5. **Normalize metric names.** Confirm the existing exporters' metric names
   match `schema.sql`/tensor-store's expectations (`cpu.utilization` style).
   If the existing deployment relabels differently, add an OTel Collector
   processor on *this platform's* side to remap — don't touch the source
   exporters' config, other consumers depend on it.

6. **Canary first.** Point the collector at a small node subset, confirm
   `metrics_raw` populates and null-segment detection behaves, before
   scraping the full fleet:

   ```sql
   SELECT count() FROM metrics_raw WHERE ts > now() - 60;
   -- expect ~= nodes * metrics * (60 / scrape_interval)
   ```

7. **If direct double-scraping is against site policy** (some sites limit
   how many things can hit host-metrics endpoints), fall back to receiving
   via the existing Prometheus's remote-write or federation endpoint
   instead of a second direct scrape. This adds a dependency on their
   pipeline's retention/availability — use only if direct scrape is
   disallowed, not as the default.

---

## Option B — fresh data collection, install on compute nodes

Use when the cluster has no existing monitoring stack, or when policy
requires this platform's own collectors end to end.

1. **Install standard exporters on every compute node** via the example
   systemd units in `telemetry-agent/configs/`:

   ```bash
   # node_exporter — CPU, mem, net, disk, load
   cp telemetry-agent/configs/node_exporter.service /etc/systemd/system/
   systemctl enable --now node_exporter
   # (unit already passes --collector.infiniband --web.listen-address=:9100)

   # dcgm-exporter — GPU nodes only, requires nvidia-dcgm.service running first
   cp telemetry-agent/configs/dcgm_exporter.service /etc/systemd/system/
   systemctl enable --now dcgm-exporter
   ```

   Roll out via Ansible/whatever config-mgmt the site uses — these units
   are examples, not a full fleet orchestration tool.

2. **Install `ib_poller.py` on every IB-equipped node:**

   ```bash
   pip install -r ingest-infra/tools/requirements.txt
   cp telemetry-agent/configs/ib_poller.service /etc/systemd/system/
   # edit unit: set NODE_ID (defaults to %H/hostname), KAFKA_BROKERS=<ingest-host>:9092
   systemctl enable --now ib_poller
   ```

   Non-IB nodes: skip, or leave installed — it polls `/sys/class/infiniband`
   and silently no-ops (logs, keeps polling) if the path is absent.

3. **Install `slurm_poller.py` once, centrally** (on the ingest host or a
   dedicated small VM — it polls `slurmrestd` every 30s, not per-node):

   ```bash
   SLURMRESTD_URL=http://<slurm-ctld-host>:6820 \
   SLURMRESTD_TOKEN=<read-scoped-token> \
   KAFKA_BROKERS=<ingest-host>:9092 \
     python3 ingest-infra/tools/slurm_poller.py
   ```

4. **Point the OTel Collector's Prometheus receiver at every node.** Edit
   `ingest-infra/otel/otel-collector-config.yaml` — replace the single
   `node-exporter:9100` / `dcgm-exporter:9400` static targets with one
   entry per real node (or a `file_sd_configs`/DNS service-discovery block
   for fleets beyond a few dozen nodes; static lists get unwieldy fast).

5. **Bring up the backend stack.** Same as Option A step 4 — HA overlay
   recommended for anything beyond first-pass validation:

   ```bash
   cd hpc-behavior-platform/ingest-infra
   docker compose -f docker-compose.ha.yml up -d
   ./ha/verify.sh
   ```

6. **Verify NTP/chrony is actually running and synced** on every node
   before trusting any cross-node timing (tensor grid alignment depends on
   it) — don't assume, check:

   ```bash
   chronyc tracking   # System time offset should be sub-second
   ```

7. **Acceptance check**, same as the docker-compose dev stack
   (`ingest-infra/README.md`):

   ```sql
   SELECT count() FROM metrics_raw WHERE ts > now() - 60;
   ```

   Nonzero, roughly `nodes * metrics * (60/interval)`, within one scrape
   interval of bringing a node online.

---

## 3. Common post-install steps (both options)

- **Single uvicorn worker only.** `analysis-api`'s `SessionStore` is an
  in-process dict, not Redis-backed. Running >1 uvicorn worker silently
  breaks session visibility across workers. Documented in
  `analysis_api/session.py`; re-stated here because it's the single
  easiest mistake when someone reflexively scales workers for throughput.

- **Recompute retention math against real data** once metrics are flowing
  — the 45-day TTL on `metrics_raw` was sized for a hypothetical worst
  case (10k nodes × 500 metrics), not this cluster's actual shape:

  ```sql
  SELECT sum(bytes_on_disk) / sum(rows) FROM system.parts WHERE table = 'metrics_raw';
  ```

  Adjust TTL in `ingest-infra/clickhouse/schema.sql` (or `ha/clickhouse/schema_ha.sql`
  if on the HA overlay) if the real bytes/row differs materially.

- **CORS / API base URL.** Both `behavior-ui`'s `VITE_API_BASE` and the
  API's `CORS_ORIGINS` are hardcoded to `localhost` in dev — set both to
  this environment's real hostnames before exposing the UI.

- **No auth layer ships with this platform.** See
  [admin-guide.md § Security posture](./admin-guide.md#security-posture)
  before exposing any of this beyond a trusted network segment.

- **Null-segment sanity check.** Reboot or cordon one real node during a
  run; confirm a null segment appears in `metrics_1m` at the correct
  timestamp — validates the pipeline against a real fault, not just the
  synthetic kill-test.

---

## 4. Full test coverage

This runbook covers *bring-up*. For the full phase-by-phase validation
(tensor-store perf at real scale, cluster-quality sanity checks, fault
recall, HA failover, multi-user sessions, alerting delivery), run through
`docs/test-plan-hardware-oci.md` Environment A sections in order — it's
the authoritative acceptance checklist, this doc only gets data flowing.
