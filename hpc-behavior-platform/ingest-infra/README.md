# ingest-infra — Phase 1: Telemetry Foundation

Docker-compose stack: Redpanda (topics: `otel.metrics`, `slurm.jobs`, `ib.metrics`),
ClickHouse (`metrics_raw`, `metrics_1m`, `jobs`, `node_inventory`), OTel Collector
gateway, Grafana.

## Bring up

```bash
docker compose up -d
docker compose --profile synth up -d synth-loader   # 200-node / 50-metric load gen
```

Grafana: http://localhost:3000 (anonymous admin, dev only). ClickHouse HTTP:
http://localhost:8123.

## Retention math (8 TB storage_server, 45-day TTL on `metrics_raw`)

Worst case at target scale: 10,000 nodes x 500 metrics / 15s sample interval
≈ 333,333 points/sec.

- Raw row: `ts(8B) + node_id(LowCardinality) + metric(LowCardinality) + value(8B, Gorilla-coded)`.
  LowCardinality dictionary-encodes repeated node/metric strings to ~2-4 bytes/row
  each; Gorilla+ZSTD on `value` typically compresses time-adjacent float64 series
  5-10x for slowly-varying telemetry.
- Effective on-disk cost: ~3-6 bytes/row after compression (measured range for
  this shape of data; verify against real workload and adjust TTL below).
- 333,333 rows/s x 86,400 s/day ≈ 28.8B rows/day x ~4 bytes/row ≈ **~115 GB/day**
  at worst-case scale.
- On ~7 TB usable (8 TB minus filesystem/ClickHouse overhead): **~60 days**
  retention at worst-case scale; comfortably over 90 days at the platform's more
  typical 1,000-2,000 node / 100-200 metric analysis scale.
- `metrics_raw` TTL is set to **45 days** (conservative margin below the 60-day
  worst case). `metrics_1m` rollups are retained **1 year** (their volume is
  ~60x smaller per the aggregation window).

Re-measure actual bytes/row via
`SELECT sum(bytes_on_disk) / sum(rows) FROM system.parts WHERE table = 'metrics_raw'`
once real data lands, and adjust the TTL in `clickhouse/schema.sql` accordingly.

## Acceptance checks

1. `docker compose up` brings up the full stack; Grafana dashboard
   "HPC Live Metrics (Phase 1)" shows live rows/min and per-node CPU util.
2. `SELECT count() FROM metrics_raw WHERE ts > now() - 60` returns
   `~= nodes * metrics * (60/interval)` rows.
3. Null-segment detection: run the synth loader with `--kill-after 120
   --kill-fraction 0.05`, then confirm killed nodes have no rows past the kill
   timestamp:

   ```bash
   python tools/synth_nodes.py --nodes 200 --metrics 50 --interval 5 \
     --duration 300 --kill-after 120 --kill-fraction 0.05 \
     --clickhouse-host localhost
   ```

   See `tools/test_null_segments.py` for the scripted version of this check.

## Custom collectors (only two permitted, per project spec)

- `tools/ib_poller.py` — reads `/sys/class/infiniband/*/ports/*/counters/*`
  (retries, symbol errors, link_downed, congestion) and publishes to
  `ib.metrics`. Standard node_exporter IB collector doesn't expose these
  uniformly across HCA vendors.
- `tools/slurm_poller.py` — polls `slurmrestd` every 30s centrally (not
  per-node) and publishes job state to `slurm.jobs`.

Everything else (CPU/mem/net/disk via node_exporter, GPU via DCGM-exporter) is
standard, scraped/pushed through the OTel Collector — no custom code.
