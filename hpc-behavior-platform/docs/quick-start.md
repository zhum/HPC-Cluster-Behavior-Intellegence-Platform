# Quick Start

Brings up the dev stack, loads synthetic data, and gets you looking at clusters in the UI. Everything here runs on one machine with dev defaults — see [Deployment Options](./deployment.md) for anything beyond a laptop demo.

## Prerequisites

- Docker + Docker Compose
- Python ≥3.11 per backend package
- Node.js (for `behavior-ui`)

## 1. Bring up the ingestion stack

```bash
cd hpc-behavior-platform/ingest-infra
docker compose up -d
```

This starts Redpanda, ClickHouse, the OTel Collector, Grafana, and Redis.

- Grafana: http://localhost:3000 (anonymous admin — dev only)
- ClickHouse HTTP: http://localhost:8123 (user `default` / password `devpass`)
- Redis: host port `6380` (6379 was avoided to dodge a local port collision)

## 2. Load synthetic telemetry

```bash
docker compose --profile synth up -d synth-loader
```

Simulates 200 nodes × 50 metrics. To also exercise fault-injection / null-segment handling:

```bash
python tools/synth_nodes.py --nodes 200 --metrics 50 --interval 5 \
  --duration 300 --kill-after 120 --kill-fraction 0.05 \
  --clickhouse-host localhost
```

## 3. Install and run the analysis API

```bash
cd hpc-behavior-platform/analysis-api
pip install -e ".[dev]"
uvicorn analysis_api.main:app --reload --port 8010
```

Reads `CLICKHOUSE_HOST`/`CLICKHOUSE_PORT`/`CLICKHOUSE_PASSWORD` and `REDIS_HOST`/`REDIS_PORT` from env (defaults match the compose stack above). See [Admin Guide § Configuration](./admin-guide.md#configuration) for the full list.

## 4. Run the frontend

```bash
cd hpc-behavior-platform/behavior-ui
cp .env.example .env   # sets VITE_API_BASE=http://localhost:8010
npm install
npm run dev
```

Open http://localhost:5173.

## 5. Sanity-check with the analysis CLIs (optional)

Instead of the UI, you can drive the pipeline directly:

```bash
cd hpc-behavior-platform/analysis-core
python -m analysis_core.inter.run --start ... --end ... --resolution 60 --k 4
python -m analysis_core.intra.run --start ... --end ... --resolution 60 --k 4 --cluster 0 --band 2h
```

Both print cluster/quality summaries to stdout — useful for confirming the ingest→tensor→analysis path works before touching the UI.

## What you should see

In the UI: four coordinated views — Time Domain, Node Similarity, Metric Reading, Node Behavior. Selecting a cluster in Node Similarity should populate the other three. If clusters look like noise, check that `synth-loader` actually finished writing (`SELECT count() FROM metrics_raw` in ClickHouse) before the API session materialized its tensor.

Next: [User Guide](./user-guide.md) for what each view means, or [Deployment Options](./deployment.md) for anything beyond this laptop demo.
