# Installation & Deployment

This guide covers two paths:

1. **[Local test deployment](#part-1--local-test-deployment-docker)** — single machine, Docker Compose, synthetic data. ~15 minutes.
2. **[Production deployment](#part-2--production-deployment)** — HA backend, real HPC telemetry, hardened services.

All paths below are relative to the repo root unless stated otherwise. The platform itself lives in `hpc-behavior-platform/`.

Related docs (more depth on specific topics):

- `hpc-behavior-platform/docs/quick-start.md` — short version of Part 1
- `hpc-behavior-platform/docs/deployment.md` — deployment options overview
- `hpc-behavior-platform/docs/admin-guide.md` — configuration, security posture, alerting
- `hpc-behavior-platform/docs/runbook-raw-hardware.md` — compute-node collector rollout
- `hpc-behavior-platform/docs/test-plan-hardware-oci.md` — acceptance checklist for real hardware / OCI

> The root-level `0-docker-compose.yml` / `0-init.sh` are early Phase 0 scaffolding. **Do not use them**; everything below uses `hpc-behavior-platform/ingest-infra/`.

---

## Components at a glance

| Component | Path | Runs as | Default port(s) |
|---|---|---|---|
| Redpanda (Kafka API) | `ingest-infra/docker-compose*.yml` | container | 9092 (dev), 9093 (HA), admin 9644 |
| ClickHouse | `ingest-infra/clickhouse/schema.sql` | container | HTTP 8123 / native 9000 (dev); 8124, 8125 / 9001, 9002 (HA) |
| ClickHouse Keeper ×3 | `ingest-infra/ha/` | container (HA only) | internal |
| MinIO (S3 cold tier) | `ingest-infra/docker-compose.ha.yml` | container (HA only) | 9100 (S3), 9101 (console) |
| OTel Collector | `ingest-infra/otel/otel-collector-config.yaml` | container | 4317 gRPC, 4318 HTTP |
| Redis (stage cache) | `ingest-infra/docker-compose.yml` | container | 6380 on host → 6379 in container |
| Grafana | `ingest-infra/grafana/` | container | 3000 |
| `tensor-store` | `hpc-behavior-platform/tensor-store` | Python library | — |
| `analysis-core` | `hpc-behavior-platform/analysis-core` | Python library + CLIs | — |
| `analysis-api` | `hpc-behavior-platform/analysis-api` | FastAPI / uvicorn | 8010 |
| `behavior-ui` | `hpc-behavior-platform/behavior-ui` | Vite dev server / static files | 5173 (dev) |
| `alerting` | `hpc-behavior-platform/alerting` | Python daemon | — |
| Node collectors | `telemetry-agent/configs/`, `ingest-infra/tools/` | systemd on compute nodes | 9100 node_exporter, 9400 dcgm-exporter |

Data flow: compute-node exporters → OTel Collector → Redpanda → ClickHouse → `tensor-store` → `analysis-core` → `analysis-api` → `behavior-ui`. `alerting` reads ClickHouse directly on a schedule.

> **Package dependency note.** `analysis-api` and `alerting` import `tensor_store` and `analysis_core`, but their `pyproject.toml` files do **not** declare them. Install `tensor-store` and `analysis-core` into the **same** virtualenv first, or the API fails at startup with `ModuleNotFoundError: No module named 'tensor_store'`.

---

# Part 1 — Local test deployment (Docker)

Everything runs on one machine with dev credentials. Not for anything network-exposed.

## 1.1 Prerequisites

| Tool | Version | Check |
|---|---|---|
| Docker Engine | 24+ | `docker version` |
| Docker Compose plugin | v2 | `docker compose version` |
| Python | ≥ 3.11 | `python3 --version` |
| Node.js | ≥ 20.19 or ≥ 22.12 (Vite 8) | `node --version` |
| RAM | 8 GB free recommended | |

Free host ports needed: `3000 4317 4318 5173 6380 8010 8123 9000 9092 9644`. Check:

```bash
for p in 3000 4317 4318 5173 6380 8010 8123 9000 9092 9644; do
  ss -ltn "sport = :$p" | grep -q LISTEN && echo "port $p in use"
done
```

If a port is taken, edit the host side of the `ports:` mapping in `hpc-behavior-platform/ingest-infra/docker-compose.yml` and set the matching env var later (see [1.5](#15-run-the-analysis-api)).

## 1.2 Clone

```bash
git clone <repo-url> HPC-Cluster-Behavior-Intellegence-Platform
cd HPC-Cluster-Behavior-Intellegence-Platform/hpc-behavior-platform
export HBP=$PWD        # used in the commands below
```

## 1.3 Start the infrastructure stack

```bash
cd $HBP/ingest-infra
docker compose up -d
docker compose ps
```

Starts Redpanda (+ one-shot `redpanda-topics` job that creates `otel.metrics`, `slurm.jobs`, `ib.metrics`), ClickHouse, OTel Collector, Grafana, Redis. The ClickHouse schema (`clickhouse/schema.sql`) is applied automatically on **first** start of the empty `clickhouse_data` volume.

Wait until ClickHouse and Redpanda report `healthy`, then verify:

```bash
curl -s http://localhost:8123/ping                                   # Ok.
curl -s -u default:devpass 'http://localhost:8123/?query=SHOW+TABLES'
# expect: anomalies, baseline_state, jobs, metrics_1m, metrics_raw, node_inventory,
#         saved_analyses, suppression_rules (+ materialized view internals)
docker compose exec redpanda rpk topic list                          # 3 topics
docker compose exec redis redis-cli ping                             # PONG
```

Endpoints:

- Grafana — http://localhost:3000 (anonymous admin; dashboard "HPC Live Metrics")
- ClickHouse HTTP — http://localhost:8123 (`default` / `devpass`)
- Redis — `localhost:6380`

## 1.4 Load synthetic telemetry

The OTel Collector in the dev stack scrapes `node-exporter:9100` / `dcgm-exporter:9400`, which don't exist locally — so locally, data comes from the synthetic loader, which writes straight into ClickHouse.

**Option A — continuous loader in Docker** (200 nodes × 50 metrics, 15 s interval):

```bash
docker compose --profile synth up -d synth-loader
docker compose logs -f synth-loader     # Ctrl-C to stop following
```

**Option B — bounded run from the host, with fault injection** (kills 5% of nodes after 120 s, to exercise null-segment handling):

```bash
python3 -m venv $HBP/.venv-tools
$HBP/.venv-tools/bin/pip install -r $HBP/ingest-infra/tools/requirements.txt
$HBP/.venv-tools/bin/python $HBP/ingest-infra/tools/synth_nodes.py \
  --nodes 200 --metrics 50 --interval 5 --duration 300 \
  --kill-after 120 --kill-fraction 0.05 --clickhouse-host localhost
```

Confirm data is landing (let it run a few minutes before analysing — clustering on 1–2 timesteps is noise):

```bash
curl -s -u default:devpass --data-binary \
  'SELECT count(), min(ts), max(ts), uniq(node_id), uniq(metric) FROM metrics_raw FORMAT Pretty' \
  http://localhost:8123/
```

## 1.5 Run the analysis API

One virtualenv holding all three packages (install order matters — see the dependency note above):

```bash
python3 -m venv $HBP/.venv
source $HBP/.venv/bin/activate
pip install -e "$HBP/tensor-store" -e "$HBP/analysis-core" -e "$HBP/analysis-api[dev]"
```

Run it (defaults already match the dev stack; shown explicitly for clarity):

```bash
export CLICKHOUSE_HOST=localhost CLICKHOUSE_PORT=8123 CLICKHOUSE_PASSWORD=devpass
export REDIS_HOST=localhost REDIS_PORT=6380
export CORS_ORIGINS=http://localhost:5173
uvicorn analysis_api.main:app --reload --port 8010
```

Smoke test (there is no `/health` endpoint; the OpenAPI doc is the cheapest check):

```bash
curl -sf http://localhost:8010/openapi.json >/dev/null && echo API up
```

Interactive API docs: http://localhost:8010/docs

## 1.6 Run the UI

New terminal:

```bash
cd $HBP/behavior-ui
cp .env.example .env          # VITE_API_BASE=http://localhost:8010
npm ci
npm run dev
```

Open http://localhost:5173. Pick a time range covered by the synthetic data. Selecting a cluster in **Node Similarity** should populate **Time Domain**, **Metric Reading** and **Node Behavior**.

## 1.7 Optional: CLI pipeline check

Bypasses the API/UI — good for isolating whether a problem is in the backend or the frontend:

```bash
source $HBP/.venv/bin/activate
START=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%S); END=$(date -u +%Y-%m-%dT%H:%M:%S)
python -m analysis_core.inter.run --start $START --end $END --resolution 60 --k 4
python -m analysis_core.intra.run --start $START --end $END --resolution 60 --k 4 --cluster 0 --band 2h
```

## 1.8 Optional: alerting

```bash
source $HBP/.venv/bin/activate
pip install -e "$HBP/alerting"
python -m alerting.run --lookback-s 3600 --resolution 60 --k 4 --band 2h --interval-s 0
```

`--interval-s 0` runs once and exits. Add `--webhook-url <url>` to test delivery (e.g. a https://webhook.site URL). Results land in the `anomalies` table.

## 1.9 Optional: tests

```bash
# Python unit tests — no live services needed
for pkg in tensor-store analysis-core analysis-api alerting evaluation; do
  (cd $HBP/$pkg && pip install -e ".[dev]" -q && pytest -q) || echo "FAILED: $pkg"
done

# Null-segment check against the live stack
$HBP/.venv-tools/bin/python $HBP/ingest-infra/tools/test_null_segments.py

# UI end-to-end — needs stack + API + `npm run dev` running
cd $HBP/behavior-ui && npx playwright install --with-deps chromium && npx playwright test
```

## 1.10 Optional: local HA rehearsal

To rehearse the production topology on one machine (needs ~12 GB RAM):

```bash
cd $HBP/ingest-infra
docker compose -p hbp-ha -f docker-compose.ha.yml up -d
./ha/verify.sh        # ~40 s: replication, Redpanda RF=3, S3 tiering
```

Uses separate ports (ClickHouse 8124/8125, Redpanda 9093, MinIO 9100/9101), so it can run next to the dev stack. Use `-p hbp-ha` so both files (which live in the same directory) don't share the default Compose project name `ingest-infra` and warn about each other's containers as orphans.

## 1.11 Stop / reset

```bash
cd $HBP/ingest-infra
docker compose --profile synth down          # stop, keep data
docker compose --profile synth down -v       # stop AND delete ClickHouse data (schema re-applied next start)
docker compose -p hbp-ha -f docker-compose.ha.yml down -v   # if you ran the HA rehearsal
```

---

# Part 2 — Production deployment

## 2.0 Read first: gaps you must close before go-live

The current code base is a research-grade implementation. These are not deployment mistakes you can configure away by following this guide — they need a decision or code change from you:

| # | Gap | Impact | What to do |
|---|---|---|---|
| 1 | **No authentication anywhere.** `analysis-api` has no login/RBAC; `user_id` on `/analyses*` is caller-supplied and unverified. | Anyone who reaches the API can read/modify any user's saved analyses and query all telemetry. | Put API + UI behind an authenticating reverse proxy (SSO/OIDC or at minimum basic auth + TLS). Keep ClickHouse, Redis, Redpanda, MinIO on a private network. See [2.8](#28-ui--reverse-proxy-tls-auth). |
| 2 | **No Redpanda → ClickHouse sink is shipped.** The OTel Collector and pollers publish to Redpanda topics, but nothing in the repo consumes `otel.metrics` / `ib.metrics` / `slurm.jobs` into `metrics_raw` / `jobs`. Locally only `synth_nodes.py` writes to ClickHouse (directly). | With real collectors, Redpanda fills up but `metrics_raw` stays empty. | Build/choose a sink before go-live (e.g. a small consumer service, ClickHouse Kafka engine + materialized view, or Redpanda Connect). Note the collector exports `otlp_proto` encoding, which must be decoded into the `metrics_raw` (ts, node_id, metric, value) shape. |
| 3 | **Single uvicorn worker only.** `SessionStore` is an in-process dict (`analysis_api/session.py`). | `--workers >1` silently breaks sessions (session created on worker A is 404 on worker B). | Run exactly one worker per process. Scale out with multiple instances + sticky sessions at the proxy. |
| 4 | **Redpanda advertises container-internal hostnames** (`redpanda:9092`, `redpanda-1:9092`…). | Kafka clients outside the Docker network (compute-node `ib_poller`, central `slurm_poller`) connect, then fail to resolve the advertised broker. | Change `--advertise-kafka-addr` to a hostname/IP reachable from compute nodes — see [2.4](#24-storage--broker-tier-ha-overlay). |
| 5 | **Plaintext default credentials** — ClickHouse `devpass`, MinIO `minioadmin/minioadmin`, Grafana anonymous admin. | Trivial compromise. | Rotate all of them ([2.4](#24-storage--broker-tier-ha-overlay), [2.10](#210-grafana)). |
| 6 | **ClickHouse user is hard-coded** to `default` in `analysis-api` (`main.py` → `tensor_store.loader.get_client`); only the password is configurable. | Can't use a least-privilege ClickHouse user without a code change. | Accept and lock down `default` (network ACL + strong password), or add a `CLICKHOUSE_USER` env var in `analysis_api/main.py`. |
| 7 | **No Dockerfiles for `analysis-api`, `alerting`, `behavior-ui`.** | Application tier is deployed as venv + systemd + static files (this guide), not containers. | Follow [2.7](#27-analysis-api)–[2.9](#29-alerting-service), or write your own images. |
| 8 | **Request size caps** (`analysis_api/envelope.py`): N ≤ 2000 nodes, M ≤ 500 metrics, T ≤ 10000 timesteps; larger requests → HTTP 422. | Large clusters can't be analysed in one session. | Tell users to slice by node set / metric set / time range. |

## 2.1 Topology & sizing

```
 compute nodes                      ingest_server (32 vCPU / 128 GB / 2 TB NVMe)
 ─────────────                      ──────────────────────────────────────────────
 node_exporter :9100  ◄── scrape ── OTel Collector :4317/:4318
 dcgm-exporter :9400  ◄── scrape ──      │
 ib_poller ─────────── Kafka ─────► Redpanda ×3 :9092/9093
                                         │  (sink — gap #2)
 slurmrestd ◄── slurm_poller (central)   ▼
                                    storage_server (32 vCPU / 256 GB / 8 TB NVMe)
                                    ──────────────────────────────────────────────
                                    ClickHouse ×2 replicas + Keeper ×3, MinIO cold tier
                                         ▲
 users ── HTTPS ──► nginx (auth, TLS) ──► analysis-api :8010 (1 worker) ── Redis
                         └── static behavior-ui
                                    alerting daemon ──► webhook
```

Sizing is from the v2 spec. The shipped HA overlay is a **single-host** Compose file — fine for a staging box or a first production pass on one large storage server. Splitting Keeper/ClickHouse/Redpanda across physical hosts requires editing the hostnames in `ingest-infra/ha/clickhouse/common/cluster.xml`, `keeper/keeper*.xml` and the Redpanda `--seeds`/advertise flags; that is not pre-built.

Retention: `metrics_raw` TTL 45 days (HA: moved to MinIO/S3 cold tier instead of deleted); `metrics_1m` rollups 1 year. Worst-case estimate ≈ 115 GB/day at 10k nodes × 500 metrics / 15 s. Re-measure after go-live ([2.12](#212-post-deploy-verification)).

## 2.2 Host preparation (ingest and storage hosts)

```bash
# Docker Engine + Compose plugin (Debian/Ubuntu example; use your distro's method)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# Python 3.11+, Node 22 LTS (only needed on the build host for the UI), nginx
sudo apt-get install -y python3 python3-venv nginx chrony
sudo systemctl enable --now chrony

# ClickHouse wants high fd limits (compose already sets nofile=262144 per container)
# Service account for the app tier
sudo useradd --system --home /opt/hbp --shell /usr/sbin/nologin hbp
sudo mkdir -p /opt/hbp && sudo chown hbp: /opt/hbp
```

**Time sync is mandatory** on every compute node and server: the tensor builder aligns samples to a 15 s grid. Verify `chronyc tracking` shows sub-second offset everywhere.

**Firewall** (allow only from the listed sources):

| Port | On | From |
|---|---|---|
| 443 | proxy host | users |
| 4317, 4318 | ingest | compute nodes (if pushing OTLP) |
| 9092 / 9093 (Redpanda) | ingest | compute nodes (`ib_poller`), `slurm_poller` host |
| 9100, 9400 | compute nodes | ingest host (scrape) |
| 6820 (slurmrestd) | Slurm controller | `slurm_poller` host |
| 8123/8124/8125, 9000–9002, 6379/6380, 9100/9101 (MinIO), 3000 | storage / ingest | **app hosts only** — never users or compute nodes |

> Port clash: MinIO's host port **9100** collides with `node_exporter :9100` if node_exporter runs on the same host. Remap MinIO in `docker-compose.ha.yml` (e.g. `"9110:9000"`) in that case.

## 2.3 Get the code onto the servers

```bash
sudo -u hbp git clone <repo-url> /opt/hbp/src
export HBP=/opt/hbp/src/hpc-behavior-platform
```

Pin to a tag/commit you have tested; record it for rollback.

## 2.4 Storage & broker tier (HA overlay)

Work in `$HBP/ingest-infra`. Make these edits **before** first start (schema is applied only when the ClickHouse volumes are empty).

**a) Credentials.** Keep secrets out of git: create `$HBP/ingest-infra/.env` (mode 600):

```bash
CLICKHOUSE_PASSWORD=<long-random>
MINIO_ROOT_USER=<name>
MINIO_ROOT_PASSWORD=<long-random>
```

Then in `docker-compose.ha.yml` replace the literals with variables:

- `clickhouse-1` / `clickhouse-2`: `CLICKHOUSE_PASSWORD: devpass` → `CLICKHOUSE_PASSWORD: ${CLICKHOUSE_PASSWORD}`
- `minio` / `minio-init`: `minioadmin` → `${MINIO_ROOT_USER}` / `${MINIO_ROOT_PASSWORD}`
- `ha/clickhouse/common/storage.xml`: update the S3 `access_key_id` / `secret_access_key` to match MinIO (or point the `s3_cold` disk at a real S3/OCI Object Storage bucket and drop MinIO entirely).
- `ha/verify.sh` uses `default:devpass` — export the new password or edit `AUTH` before running it.

**b) Redpanda advertised address (gap #4).** For each `redpanda-N` service, make the broker reachable from outside Docker by adding an external listener, e.g. for `redpanda-1`:

```yaml
      - --kafka-addr=internal://0.0.0.0:9092,external://0.0.0.0:19092
      - --advertise-kafka-addr=internal://redpanda-1:9092,external://ingest01.example.org:19092
    ports:
      - "19092:19092"
```

(use 19093/19094 for brokers 2/3). Compute-node clients then use `KAFKA_BROKERS=ingest01.example.org:19092,ingest01.example.org:19093,ingest01.example.org:19094`.

**c) Retention.** Adjust `TTL` in `ha/clickhouse/schema_ha.sql` if your sizing differs from the defaults.

**d) Start and verify:**

```bash
cd $HBP/ingest-infra
docker compose -p hbp -f docker-compose.ha.yml up -d
docker compose -p hbp -f docker-compose.ha.yml ps      # all healthy; *-init / *-topics jobs exit 0
./ha/verify.sh
```

`verify.sh` checks that a row written to replica 1 appears on replica 2, Redpanda health and RF=3, and the tiering policy. Do not continue until it passes.

**e) Restart on reboot.** Neither Compose file sets a `restart:` policy, so containers will **not** come back after a host reboot. Add `restart: unless-stopped` to every long-running service in `docker-compose.ha.yml` (not to the one-shot `minio-init` / `redpanda-topics` jobs) before `up -d`.

## 2.5 Redis and OTel Collector

The HA overlay does **not** include Redis, the OTel Collector or Grafana. Run them on the same Docker network as the HA stack (`hbp_default` when started with `-p hbp`).

**Redis** (cache only — losing it costs recomputation, not data):

```bash
docker run -d --name hbp-redis --restart unless-stopped --network hbp_default \
  -p 127.0.0.1:6380:6379 redis:7.2-alpine \
  redis-server --requirepass '<redis-password>' --maxmemory 4gb --maxmemory-policy allkeys-lru
```

> `analysis-api` currently passes no Redis password (`main.py` builds `Redis(host, port)` only). Either keep Redis bound to `127.0.0.1` / a private network without `--requirepass`, or add `password=os.environ.get("REDIS_PASSWORD")` to that call.

**OTel Collector.** Copy and edit the config:

```bash
cp $HBP/ingest-infra/otel/otel-collector-config.yaml /opt/hbp/otel-collector-config.yaml
```

- `exporters.*.brokers`: `["redpanda:9092"]` → `["redpanda-1:9092","redpanda-2:9092","redpanda-3:9092"]`
- `receivers.prometheus...static_configs.targets`: replace `node-exporter:9100` / `dcgm-exporter:9400` with your real nodes (`node001:9100`, …), or use `file_sd_configs` for large fleets.
- Normalise metric names to what `tensor-store` expects (`cpu.utilization` style) with a `metricstransform` processor if your exporters name them differently — do not change the exporters themselves if other consumers depend on them.
- Size `memory_limiter.limit_mib` to the host.

```bash
docker run -d --name hbp-otel --restart unless-stopped --network hbp_default \
  -p 4317:4317 -p 4318:4318 \
  -v /opt/hbp/otel-collector-config.yaml:/etc/otel/config.yaml:ro \
  otel/opentelemetry-collector-contrib:0.104.0 --config=/etc/otel/config.yaml
docker logs -f hbp-otel   # look for scrape errors / Kafka connection errors
```

## 2.6 Compute-node collectors

Full procedure, including the "existing exporters already running" path: `hpc-behavior-platform/docs/runbook-raw-hardware.md`. Summary:

```bash
# every compute node (via Ansible/your config management)
cp telemetry-agent/configs/node_exporter.service /etc/systemd/system/
systemctl enable --now node_exporter

# GPU nodes only (requires nvidia-dcgm.service)
cp telemetry-agent/configs/dcgm_exporter.service /etc/systemd/system/
systemctl enable --now dcgm-exporter

# IB-equipped nodes
useradd --system telemetry
mkdir -p /opt/hpc-behavior-platform
cp ingest-infra/tools/ib_poller.py /opt/hpc-behavior-platform/
pip3 install -r ingest-infra/tools/requirements.txt
cp telemetry-agent/configs/ib_poller.service /etc/systemd/system/
# edit unit: Environment=KAFKA_BROKERS=ingest01.example.org:19092,...   (see 2.4b)
systemctl daemon-reload && systemctl enable --now ib_poller
```

`slurm_poller.py` runs **once, centrally** (ingest host is fine). Use a read-scoped `slurmrestd` token. Example unit `/etc/systemd/system/hbp-slurm-poller.service`:

```ini
[Unit]
Description=HPC Behavior Platform - Slurm job poller
After=network-online.target
Wants=network-online.target

[Service]
User=hbp
Environment=SLURMRESTD_URL=http://slurmctl01.example.org:6820
Environment=KAFKA_BROKERS=ingest01.example.org:19092,ingest01.example.org:19093,ingest01.example.org:19094
EnvironmentFile=/etc/hbp/slurm-poller.env
ExecStart=/opt/hbp/venv-tools/bin/python /opt/hbp/src/hpc-behavior-platform/ingest-infra/tools/slurm_poller.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo -u hbp python3 -m venv /opt/hbp/venv-tools
sudo -u hbp /opt/hbp/venv-tools/bin/pip install -r $HBP/ingest-infra/tools/requirements.txt
sudo install -d -m 750 -o root -g hbp /etc/hbp
echo 'SLURMRESTD_TOKEN=<token>' | sudo install -m 640 -o root -g hbp /dev/stdin /etc/hbp/slurm-poller.env
sudo systemctl daemon-reload && sudo systemctl enable --now hbp-slurm-poller
```

Roll out to a **canary subset** of nodes first and confirm data flows end to end (which requires the sink from gap #2) before adding the whole fleet.

## 2.7 analysis-api

Install:

```bash
sudo -u hbp python3 -m venv /opt/hbp/venv
sudo -u hbp /opt/hbp/venv/bin/pip install \
  "$HBP/tensor-store" "$HBP/analysis-core" "$HBP/analysis-api" "$HBP/alerting"
```

(Non-editable installs in production; reinstall on upgrade.)

Config `/etc/hbp/api.env` (mode 640, `root:hbp`):

```bash
CLICKHOUSE_HOST=127.0.0.1
CLICKHOUSE_PORT=8124
CLICKHOUSE_PASSWORD=<same as 2.4a>
REDIS_HOST=127.0.0.1
REDIS_PORT=6380
CORS_ORIGINS=https://hbp.example.org
```

`CORS_ORIGINS` is comma-separated. If the UI is served from the same origin as the API (the proxy layout in 2.8), CORS isn't exercised, but set it correctly anyway.

> ClickHouse HA has no load balancer in front of it. Point the API at one replica (8124); if it goes down, switch `CLICKHOUSE_PORT` to 8125 and restart. Put HAProxy/chproxy in front if you need automatic failover.

Unit `/etc/systemd/system/hbp-api.service`:

```ini
[Unit]
Description=HPC Behavior Platform - analysis API
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=hbp
EnvironmentFile=/etc/hbp/api.env
# Exactly ONE worker: SessionStore is in-process (see INSTALL.md gap #3)
ExecStart=/opt/hbp/venv/bin/uvicorn analysis_api.main:app --host 127.0.0.1 --port 8010 --workers 1 --proxy-headers
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/hbp

[Install]
WantedBy=multi-user.target
```

`ReadWritePaths=/opt/hbp` is there because `tensor-store` keeps an on-disk tensor cache at `$HOME/.cache/hpc-behavior-platform/tensor-store` (`/opt/hbp/.cache/...` for the `hbp` user). It is not size-bounded — watch its disk usage.

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now hbp-api
curl -sf http://127.0.0.1:8010/openapi.json >/dev/null && echo API up
journalctl -u hbp-api -f
```

Restarting the API drops all live analysis sessions (they're in memory); saved analyses in ClickHouse survive. Schedule restarts accordingly.

## 2.8 UI + reverse proxy (TLS, auth)

Build the UI with the public API URL baked in (Vite inlines `VITE_API_BASE` at build time):

```bash
cd $HBP/behavior-ui
echo 'VITE_API_BASE=https://hbp.example.org/api' > .env.production
npm ci && npm run build                       # output: dist/
sudo install -d /var/www/hbp && sudo cp -r dist/. /var/www/hbp/
```

nginx `/etc/nginx/sites-available/hbp` — UI and API on one origin, authentication at the proxy:

```nginx
server {
    listen 80;
    server_name hbp.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name hbp.example.org;

    ssl_certificate     /etc/letsencrypt/live/hbp.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hbp.example.org/privkey.pem;

    # Minimum viable auth. Prefer SSO (oauth2-proxy / your IdP) in front instead.
    auth_basic           "HPC Behavior Platform";
    auth_basic_user_file /etc/nginx/hbp.htpasswd;

    root /var/www/hbp;
    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8010/;      # trailing slash strips /api
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;                # session materialisation can be slow
        client_max_body_size 10m;
    }
}
```

```bash
sudo htpasswd -c /etc/nginx/hbp.htpasswd <user>     # apache2-utils
sudo ln -s /etc/nginx/sites-available/hbp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> Proxy auth protects the endpoints, but `user_id` inside the app is still unverified (gap #1): any authenticated user can access any other user's saved analyses. If that matters, inject the authenticated username from the proxy and enforce it in `analysis_api/routers/analyses.py`.

To scale beyond one API process: run several `hbp-api@<port>` instances (each `--workers 1`) and use `upstream { hash $cookie_<session-cookie> consistent; ... }` or `ip_hash` for stickiness.

## 2.9 Alerting service

`/etc/systemd/system/hbp-alerting.service`:

```ini
[Unit]
Description=HPC Behavior Platform - anomaly alerting
After=network-online.target hbp-api.service

[Service]
User=hbp
EnvironmentFile=/etc/hbp/alerting.env
ExecStart=/bin/sh -c 'exec /opt/hbp/venv/bin/python -m alerting.run \
  --lookback-s 3600 --resolution 60 --k 4 --band 2h --interval-s 300 \
  --clickhouse-host 127.0.0.1 --clickhouse-port 8124 \
  --clickhouse-password "$CLICKHOUSE_PASSWORD" --webhook-url "$WEBHOOK_URL"'
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

`/etc/hbp/alerting.env` (mode 640, `root:hbp`):

```bash
CLICKHOUSE_PASSWORD=<same as 2.4a>
WEBHOOK_URL=https://hooks.example.org/hbp
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now hbp-alerting
```

Note the password is visible in the process list via argv (the CLI only takes it as a flag). Anomalies persist to the `anomalies` table even when webhook delivery fails. Dismissals are rows in `suppression_rules` (no UI yet).

## 2.10 Grafana

Optional (cluster-telemetry dashboards, not platform health). Run with auth enabled:

```bash
docker run -d --name hbp-grafana --restart unless-stopped --network hbp_default \
  -p 127.0.0.1:3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD='<admin-password>' \
  -e GF_AUTH_ANONYMOUS_ENABLED=false \
  -e GF_INSTALL_PLUGINS=grafana-clickhouse-datasource \
  -v $HBP/ingest-infra/grafana/provisioning:/etc/grafana/provisioning:ro \
  -v hbp_grafana:/var/lib/grafana \
  grafana/grafana:11.1.0
```

Edit `ingest-infra/grafana/provisioning/datasources/clickhouse.yaml` to point at `clickhouse-1` with the new password first. Expose via nginx if needed.

## 2.11 Backups and upgrades

- **Schema changes:** `docker-entrypoint-initdb.d` runs only on an empty volume. On an existing deployment apply DDL manually on **each** replica (the HA schema deliberately avoids `ON CLUSTER`). Don't switch `saved_analyses` soft-delete to `ALTER ... DELETE` (see admin guide).
- **Backups:** ClickHouse `BACKUP DATABASE default TO S3(...)` (or `clickhouse-backup`) on a schedule. At minimum back up `saved_analyses`, `baseline_state`, `suppression_rules`, `node_inventory` — raw metrics are large and partially reproducible; small state tables are not.
- **App upgrade:** `git -C /opt/hbp/src fetch && git checkout <tag>` → reinstall wheels into `/opt/hbp/venv` → rebuild UI → `systemctl restart hbp-api hbp-alerting`. Users lose live sessions on restart.
- **Rollback:** check out the previous tag and repeat. Schema changes are not auto-reverted.

## 2.12 Post-deploy verification

```bash
CH="curl -s -u default:$CLICKHOUSE_PASSWORD http://127.0.0.1:8124/"

# data is flowing (expect ≈ nodes × metrics × 60/interval)
$CH --data-binary 'SELECT count() FROM metrics_raw WHERE ts > now() - 60'

# replicas healthy, no queue backlog
$CH --data-binary 'SELECT table, is_readonly, absolute_delay, queue_size FROM system.replicas FORMAT Pretty'

# real bytes/row, to validate the 45-day TTL
$CH --data-binary "SELECT sum(bytes_on_disk)/sum(rows) FROM system.parts WHERE table='metrics_raw' AND active"

# Redpanda consumer lag (once your sink exists)
docker compose -p hbp -f $HBP/ingest-infra/docker-compose.ha.yml exec redpanda-1 rpk group list

# app tier
systemctl is-active hbp-api hbp-alerting hbp-slurm-poller
curl -sf -u <user>:<pass> https://hbp.example.org/api/openapi.json >/dev/null && echo OK
```

Then:

1. Open https://hbp.example.org, create a session over the last hour, confirm the four views populate.
2. Reboot or drain one canary node; confirm a null segment appears in `metrics_1m` at the right timestamp.
3. Work through `hpc-behavior-platform/docs/test-plan-hardware-oci.md` (Env A for on-prem, Env B for OCI) and fill in its sign-off table.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: tensor_store` / `analysis_core` when starting API or alerting | Undeclared deps not installed in that venv | Install `tensor-store` and `analysis-core` into the same venv |
| API returns 404 for a session that was just created | More than one uvicorn worker, or API restarted | `--workers 1`; recreate session after restarts |
| API returns 422 on session create | Request exceeds N/M/T caps | Narrow node set, metric set or time range |
| Browser console: CORS error | `CORS_ORIGINS` doesn't match UI origin exactly (scheme + host + port) | Fix env var, restart API |
| UI calls `localhost:8010` in production | `VITE_API_BASE` not set at **build** time | Set `.env.production`, rebuild |
| `Address already in use` on `docker compose up` | Host port clash (6379, 9100, 3000 are common) | Remap host side of the `ports:` entry |
| `ib_poller` logs Kafka connection errors / unknown host `redpanda` | Broker advertises internal name | Section 2.4b |
| `metrics_raw` empty in production while Redpanda topics fill | No sink (gap #2) | Implement sink |
| `metrics_raw` empty locally | `synth-loader` not started, or started before ClickHouse was healthy | `docker compose --profile synth up -d synth-loader`; check its logs |
| Clusters look like noise | Too few timesteps in window | Let loader run longer; widen time range |
| Alerting reports stale results | Tensor disk cache reuse | Polling consumers must call `get_tensor(..., use_cache=False)` (alerting already does) |
| Keeper container unhealthy in HA | Healthcheck targeting `localhost` / 4lw commands disabled | See `ingest-infra/ha/README.md` |
| Schema edits not taking effect | initdb scripts only run on empty volume | Apply DDL manually, or `down -v` (destroys data) in dev |
