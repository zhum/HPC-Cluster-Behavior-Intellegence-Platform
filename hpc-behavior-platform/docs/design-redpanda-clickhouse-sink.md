# Design: Redpanda → ClickHouse sink

Status: **implemented** (2026-10-30). Closes INSTALL.md gap #2.

Implemented as designed, with these differences / findings:

- All 22 platform metrics used by `synth_nodes.py` are mapped in the edge collector. Beyond §1a's table:
  - `memory.used` = MemTotal − MemAvailable, `memory.swap` = SwapTotal − SwapFree, `storage.latency` = Δ(read+write time) / Δ(completed I/Os), in seconds per I/O — via `experimental_metricsgeneration`. That processor needs contrib ≥ 0.110, so the **edge** collector runs 0.110.0; the sink stays on 0.104.0 because the landing-table schema is pinned to it.
  - `memory.page_faults` (`node_vmstat_pgfault`) and `network.retransmits` (`node_netstat_Tcp_RetransSegs`) are untyped in node_exporter; converted to cumulative sums with OTTL before the rate step.
  - `gpu.ecc_errors` = rate of SBE + DBE volatile ECC counts; `gpu.nvlink_tx/rx` = `DCGM_FI_PROF_NVLINK_{TX,RX}_BYTES` summed over GPUs. dcgm-exporter's default counters file has ECC commented out and no NVLink byte fields, so `telemetry-agent/configs/dcgm-counters.csv` ships the needed list and the systemd unit passes it with `-f`.
- The edge config's unused `kafka/ib_metrics` exporter was removed (`ib_poller` publishes to Kafka itself), and the `logging` exporter replaced by `debug` (removed in contrib 0.111).
- Verified locally: all three paths on the dev stack (10 node_exporter metrics landing with only `node_id`; IB row; Slurm running→completed collapsing to one row under `FINAL`; garbage message in `sink_errors`) and on the HA overlay (rows on both replicas, both sink collectors in one group). **HA failover worked but was slow:** with `clickhouse-1` stopped, `clickhouse-2` took over the Kafka partition after 2–4 minutes; no data lost. Tune librdkafka session timeouts in ClickHouse's `<kafka>` config if that matters.
- DCGM tested on one GeForce RTX 4080 SUPER only: util/memory/power/temp/ECC land (ECC is 0 — no ECC on consumer GPUs, and dcgm-exporter emits empty values without breaking the scrape). NVLink fields are skipped there (`metric not enabled`: no profiling on consumer GPUs, no NVLink) — untested on datacenter GPUs. DCGM profiling fields can also be unavailable when another profiler (Nsight, DCGM in another container) holds the profiling lock.

## Problem

Producers publish to three Redpanda topics, but nothing consumes them. Only `tools/synth_nodes.py` writes to ClickHouse (directly, bypassing Redpanda), so on real hardware `metrics_raw` and `jobs` stay empty.

| Topic | Producer | Encoding | Target table |
|---|---|---|---|
| `otel.metrics` | OTel Collector (`kafka/otel_metrics` exporter) | `otlp_proto` — nested ResourceMetrics → ScopeMetrics → Metric → DataPoint | `metrics_raw` |
| `ib.metrics` | `tools/ib_poller.py`, per node, 15 s | JSON, one object per (hca, port, counter) | `metrics_raw` |
| `slurm.jobs` | `tools/slurm_poller.py`, central, 30 s | JSON, one object per job per poll | `jobs` |

Target shapes (`clickhouse/schema.sql`):

```sql
metrics_raw (ts DateTime64(3), node_id LowCardinality(String), metric LowCardinality(String), value Float64)
jobs        (job_id, user, partition, node_list Array(String), state, start_time DateTime,
             end_time Nullable(DateTime), exit_code Nullable(Int32), priority Nullable(UInt32))  -- ReplacingMergeTree
```

## Constraints

- v2 spec: only two custom collectors (`ib_poller`, `slurm_poller`); everything else standard. A sink isn't a collector, but the same "no custom code where a standard component works" applies.
- Must work on both the dev stack and the HA overlay (2 replicas, 3 brokers, no `ON CLUSTER` DDL).
- `tensor-store` reads `metrics_raw` with `argMax(value, ts)` per `(grid cell, node_id, metric)` (`tensor_store/loader.py`) — duplicate rows are harmless, so **at-least-once delivery is enough** for metrics.
- `analysis-api` caps M ≤ 500 metrics per session — raw node_exporter output (per-CPU × per-mode series) blows past that; metrics must be curated before landing.
- Analysis assumes rates/levels, not monotonic counters (z-scores on a cumulative counter are meaningless).

## Decision

Two standard mechanisms, split by encoding:

1. **`otel.metrics`** → a second OTel Collector ("sink collector": `kafka` receiver → `clickhouse` exporter) writing into **`Null`-engine landing tables**, with a ClickHouse materialized view projecting into `metrics_raw`. Curation (renaming, rates, label aggregation) happens in the **edge** collector, before Kafka.
2. **`ib.metrics`, `slurm.jobs`** → ClickHouse **Kafka table engine** + materialized views. Flat JSON is exactly what `JSONEachRow` reads.

No new custom service. Redpanda stays the buffer for all three streams.

### Alternatives considered

| Option | Why not |
|---|---|
| Kafka engine + `Protobuf` format for OTLP | OTLP's nesting and `oneof` data-point types map poorly onto ClickHouse's Protobuf input; fragile, and node_exporter label curation would still need doing somewhere |
| Switch edge exporter to `otlp_json`, unpack in SQL with `JSONExtract`/`arrayJoin` | Four levels of nested arrays in an MV; unreadable, slow at 333k points/s |
| Custom Python consumer (kafka-python + opentelemetry-proto) | Works, but it's a new service to own, scale and monitor; standard components cover it |
| Edge collector writes ClickHouse directly (no Kafka for node metrics) | Drops Redpanda as the buffer — ClickHouse maintenance would lose data |
| Redpanda Connect | Another runtime to operate; no advantage over the above for these shapes |

## 1. Node metrics: `otel.metrics` → `metrics_raw`

```
node_exporter/dcgm ─scrape─► edge collector ─otlp_proto─► otel.metrics ─► sink collector ─► otel_metrics_{gauge,sum,...} (Null)
                             (relabel, rate,                               (kafka recv,         │ MV
                              rename, aggregate)                            clickhouse exp)     ▼
                                                                                            metrics_raw
```

### 1a. Edge collector changes (`otel/otel-collector-config.yaml`)

All curation lives here, because rate conversion is stateful per series and the edge collector is the one instance that sees every sample of a given series (it scrapes it). The sink collector then stays stateless and can scale with Kafka partitions.

- **node_id**: add a scrape relabel so every point carries it explicitly, independent of OTel semantic-convention versions:
  ```yaml
  relabel_configs:
    - source_labels: [__address__]
      regex: '([^:]+):\d+'
      target_label: node_id
  ```
- **Allow-list** (`filter` processor): keep only the series that map to platform metrics; drop everything else (Go runtime, scrape meta, histograms).
- **Counters → rates**: `cumulativetodelta` then `deltatorate` processors (both in contrib 0.104). First sample after a restart is dropped; counter resets are handled.
- **Rename + aggregate** (`metricstransform`): map exporter names onto the platform names already used by `synth_nodes.py` and expected by the UI, and collapse high-cardinality labels so M stays well under 500. Starting mapping (to be completed against real exporter output in test plan §0.1.5):

  | Platform metric | Source | Aggregation |
  |---|---|---|
  | `cpu.utilization` | `node_cpu_seconds_total` rate, mode≠idle | sum over `cpu`,`mode` ÷ core count (or `1 - idle`) |
  | `cpu.load_avg` | `node_load1` | — |
  | `cpu.context_switches` | `node_context_switches_total` rate | — |
  | `cpu.interrupts` | `node_intr_total` rate | — |
  | `memory.used` / `memory.free` | `node_memory_MemTotal_bytes - MemAvailable_bytes` / `MemAvailable_bytes` | — |
  | `network.rx_bytes` / `tx_bytes` | `node_network_{receive,transmit}_bytes_total` rate | sum over `device` (exclude `lo`) |
  | `storage.iops` | `node_disk_{reads,writes}_completed_total` rate | sum over `device` |
  | `gpu.utilization` | `DCGM_FI_DEV_GPU_UTIL` | mean over `gpu` |
  | `gpu.power` / `gpu.temperature` | `DCGM_FI_DEV_POWER_USAGE` / `DCGM_FI_DEV_GPU_TEMP` | mean/max over `gpu` |

  Aggregations that need arithmetic between two metrics (`memory.used`, `cpu.utilization` as `1 - idle`) use the `transform` processor or are expressed as a simpler proxy; decide per metric when filling in the table.
- After aggregation only `node_id` remains as a data-point attribute. Anything else surviving is a curation bug — the MV below ignores it, so two series would collapse onto one `(node_id, metric)` and `argMax` would pick one arbitrarily.

### 1b. Sink collector (new compose service `otel-sink`)

Same image as the edge collector (`otel/opentelemetry-collector-contrib:0.104.0`), new config `otel/otel-sink-config.yaml`:

```yaml
receivers:
  kafka:
    brokers: ["redpanda:9092"]          # HA: redpanda-1..3
    topic: otel.metrics
    encoding: otlp_proto
    group_id: hbp-clickhouse-sink
    initial_offset: earliest

processors:
  batch:
    send_batch_size: 50000
    timeout: 5s

exporters:
  clickhouse:
    endpoint: tcp://clickhouse:9000?dial_timeout=10s
    database: default
    username: default
    password: ${env:CLICKHOUSE_PASSWORD}
    create_schema: false                # landing tables are pre-created as Null (1c)
    timeout: 10s
    retry_on_failure: {enabled: true, max_elapsed_time: 0}   # never drop; Kafka offset not committed until export succeeds
    sending_queue: {enabled: true, queue_size: 100}

service:
  pipelines:
    metrics:
      receivers: [kafka]
      processors: [batch]
      exporters: [clickhouse]
```

Scaling: run N replicas with the same `group_id`; raise `otel.metrics` partitions to ≥ N (topics are currently created with the default 1 partition).

### 1c. ClickHouse landing tables + MV (new `clickhouse/sink.sql`, runs after `schema.sql` in initdb order)

The exporter inserts into `otel_metrics_gauge`, `otel_metrics_sum`, `otel_metrics_histogram`, `otel_metrics_summary`, `otel_metrics_exponential_histogram` with an explicit column list. Create all five with `ENGINE = Null`: rows pass through the MV and are never stored — no duplicate storage, nothing to replicate or TTL.

Getting the column lists right: **don't hand-transcribe them.** Generate once per collector version:

```bash
# scratch ClickHouse, exporter with create_schema: true, send one batch, then:
for t in gauge sum histogram summary exponential_histogram; do
  clickhouse-client -q "SHOW CREATE TABLE otel_metrics_$t" | sed 's/ENGINE = .*/ENGINE = Null/'
done
```

Commit the output as `sink.sql` and pin the collector image tag; bumping the tag means regenerating.

```sql
-- after the generated Null tables:
CREATE MATERIALIZED VIEW IF NOT EXISTS otel_gauge_to_raw_mv TO metrics_raw AS
SELECT toDateTime64(TimeUnix, 3) AS ts,
       Attributes['node_id']    AS node_id,
       MetricName               AS metric,
       Value                    AS value
FROM otel_metrics_gauge
WHERE node_id != '' AND isFinite(value);

-- deltatorate emits gauges, but keep a sum MV so a mis-curated counter still lands (and shows up in review)
CREATE MATERIALIZED VIEW IF NOT EXISTS otel_sum_to_raw_mv TO metrics_raw AS
SELECT toDateTime64(TimeUnix, 3) AS ts, Attributes['node_id'] AS node_id,
       MetricName AS metric, Value AS value
FROM otel_metrics_sum
WHERE node_id != '' AND isFinite(value);
```

Histogram/summary/exponential tables have no MV: data reaching them is discarded by design (the edge filter shouldn't let any through).

## 2. InfiniBand: `ib.metrics` → `metrics_raw`

### 2a. `ib_poller.py` change (required)

It currently publishes raw cumulative sysfs counters, one record per (hca, port, counter). Change it to keep the previous reading per key and publish **one record per (node, counter) per poll: the per-second rate summed over all HCAs/ports**:

```json
{"ts": "2026-10-30T09:00:15.000+00:00", "node_id": "node017", "metric": "ib.symbol_errors", "value": 0.0}
```

- Rate needs state across polls; the poller is the only place that has it per node.
- Summing across ports keeps M at 4 and identical on every node (8-HCA GPU nodes and 1-HCA CPU nodes become comparable). Per-port localisation is lost in ClickHouse; if needed later, add `hca`/`port` back into the JSON for forensics — the MV ignores extra keys.
- Counter reset (value < previous) → skip that sample, don't emit a negative rate.
- First poll after start emits nothing.

### 2b. ClickHouse (in `sink.sql`)

```sql
CREATE TABLE IF NOT EXISTS ib_metrics_queue
(
    ts      String,
    node_id String,
    metric  String,
    value   Float64
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'ib.metrics',
         kafka_group_name = 'hbp-clickhouse-ib',
         kafka_format = 'JSONEachRow',
         kafka_handle_error_mode = 'stream';

CREATE MATERIALIZED VIEW IF NOT EXISTS ib_metrics_mv TO metrics_raw AS
SELECT parseDateTime64BestEffort(ts, 3) AS ts, node_id, metric, value
FROM ib_metrics_queue
WHERE length(_error) = 0;
```

`ts` lands as `String` and is parsed in the MV because the poller emits ISO-8601 with offset, which `JSONEachRow` won't coerce into `DateTime64` under default settings.

## 3. Slurm: `slurm.jobs` → `jobs`

### 3a. `slurm_poller.py` changes (required — current output is wrong)

- **`node_list`**: slurmrestd returns a hostlist expression (`gpu[001-004],cpu017`); the poller splits on `,`, producing `["gpu[001-004]", "cpu017"]`, which never matches `node_id`s, so the jobs overlay in the UI would never find a job. Expand the hostlist in the poller (`scontrol show hostnames` is not available on every poller host; a ~20-line bracket-range expander with a test is enough).
- **`exit_code`**: in API `v0.0.40` `exit_code.return_code` is a `{set, infinite, number}` object, not an int — unwrap `.number` like `start_time` already does. Verify against the real slurmrestd version in test-plan §0.
- **Pending jobs** (`start_time` 0 / unset): skip them. `jobs` is `ORDER BY (start_time, job_id)`; publishing a job first with start 0 and later with its real start creates two rows that `ReplacingMergeTree` will never merge.

### 3b. ClickHouse (in `sink.sql`)

```sql
CREATE TABLE IF NOT EXISTS slurm_jobs_queue
(
    job_id     String,
    user       String,
    partition  String,
    node_list  Array(String),
    state      String,
    start_time UInt64,
    end_time   Nullable(UInt64),
    exit_code  Nullable(Int32),
    priority   Nullable(UInt32),
    polled_at  String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'slurm.jobs',
         kafka_group_name = 'hbp-clickhouse-slurm',
         kafka_format = 'JSONEachRow',
         kafka_handle_error_mode = 'stream';

CREATE MATERIALIZED VIEW IF NOT EXISTS slurm_jobs_mv TO jobs AS
SELECT job_id, user, partition, node_list, state,
       toDateTime(start_time)                              AS start_time,
       if(end_time > 0, toDateTime(end_time), NULL)        AS end_time,
       exit_code, priority
FROM slurm_jobs_queue
WHERE length(_error) = 0 AND start_time > 0;
```

### 3c. Read side (required)

Every job is re-published every 30 s, so `jobs` holds many unmerged copies. `analysis_api/routers/jobs.py` queries without `FINAL` → duplicated intervals in the UI. Add `FINAL` to that query. (`ReplacingMergeTree` without a version column keeps the last-inserted row, which is the latest poll — correct here.)

## 4. Dead letters (all Kafka-engine streams)

`kafka_handle_error_mode = 'stream'` sends unparseable messages to the `_error` / `_raw_message` virtual columns instead of stalling the consumer. Capture them:

```sql
CREATE TABLE IF NOT EXISTS sink_errors
(
    at      DateTime DEFAULT now(),
    topic   LowCardinality(String),
    error   String,
    raw     String
)
ENGINE = MergeTree ORDER BY at TTL at + INTERVAL 7 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ib_errors_mv TO sink_errors AS
SELECT _topic AS topic, _error AS error, _raw_message AS raw FROM ib_metrics_queue WHERE length(_error) > 0;

CREATE MATERIALIZED VIEW IF NOT EXISTS slurm_errors_mv TO sink_errors AS
SELECT _topic AS topic, _error AS error, _raw_message AS raw FROM slurm_jobs_queue WHERE length(_error) > 0;
```

The OTLP path has no DLQ: the sink collector retries forever and Kafka holds the backlog; a persistent failure shows as consumer lag (§7).

## 5. HA overlay

- `ha/clickhouse/sink_ha.sql`: same DDL; `sink_errors` → `ReplicatedMergeTree` (needs the explicit replica-name argument, see `ha/README.md`); broker list `redpanda-1:9092,redpanda-2:9092,redpanda-3:9092`. Mount it on both replicas after `schema_ha.sql`.
- Kafka-engine tables exist on **both** replicas with the **same** group name → the brokers split partitions between them; each writes to its local `Replicated*` table, which replicates. If a replica dies, the group rebalances to the survivor.
- Null landing tables and MVs exist on both replicas. Run one sink collector per replica (`otel-sink-1` → `clickhouse-1`, `otel-sink-2` → `clickhouse-2`), same `group_id`: if a replica is down its collector stalls without committing offsets and the group rebalances its partitions to the healthy one.
- Partitions: create topics with `-p` ≥ number of consumers (ClickHouse replicas × `kafka_num_consumers`, sink collector replicas). Today they are created with 1 partition, meaning one active consumer per group — fine for failover, a ceiling for throughput.
- No `ON CLUSTER` (consistent with existing HA DDL).

## 6. Delivery semantics

| Stream | Guarantee | Duplicate effect |
|---|---|---|
| `otel.metrics` | at-least-once (collector commits offset after export) | none — `argMax` per grid cell |
| `ib.metrics` | at-least-once (Kafka engine commits after block insert) | none — same |
| `slurm.jobs` | at-least-once | collapsed by `ReplacingMergeTree` + `FINAL` |

Ordering across partitions is irrelevant: everything is keyed by timestamp.

## 7. Operations

```sql
-- per-stream freshness
SELECT metric LIKE 'ib.%' AS ib, max(ts), count() FROM metrics_raw WHERE ts > now() - 300 GROUP BY ib;
SELECT max(start_time), count() FROM jobs FINAL;
-- parse failures
SELECT topic, count(), any(error) FROM sink_errors WHERE at > now() - 3600 GROUP BY topic;
-- Kafka engine consumer state (24.3+)
SELECT database, table, num_messages_read, last_exception FROM system.kafka_consumers;
```

```bash
rpk group describe hbp-clickhouse-sink      # lag on otel.metrics
rpk group describe hbp-clickhouse-ib
rpk group describe hbp-clickhouse-slurm
```

Alert on: lag growing for > 5 min, `sink_errors` non-empty, `metrics_raw` max(ts) older than 2× scrape interval.

Pausing ingestion for ClickHouse maintenance: `DETACH TABLE ib_metrics_queue` / `slurm_jobs_queue`, stop `otel-sink`; Redpanda retains the backlog (check topic `retention.ms` covers the window), reattach/start to drain.

## 8. Test plan

Local, on the dev compose stack:

1. Add a `node-exporter` service (`prom/node-exporter`) to `docker-compose.yml` — the edge config already scrapes `node-exporter:9100`, but the service doesn't exist, so the OTLP path is untestable locally today. Add `otel-sink` and mount `sink.sql`.
2. `docker compose down -v && up -d` (initdb only runs on an empty volume).
3. OTLP path: within ~1 min, `SELECT DISTINCT metric FROM metrics_raw WHERE node_id = 'node-exporter'` returns the curated names only, all < 500, none ending in `_total`.
4. IB path: `rpk topic produce ib.metrics` a valid record and a garbage line → one row in `metrics_raw`, one in `sink_errors`.
5. Slurm path: produce a running job with `node_list: ["n1","n2"]`, then the same job completed → `SELECT count() FROM jobs FINAL WHERE job_id = ...` = 1 with `end_time` set; a pending job (start 0) → no row.
6. Kill `clickhouse` for 2 min while producing; restart → no gap in `metrics_raw` (backlog drained).
7. Unit tests: hostlist expander and IB rate/reset logic in `ingest-infra/tools/` (pure functions, no Kafka needed).
8. HA: repeat 3–6 against `docker-compose.ha.yml`; additionally stop `clickhouse-1` and confirm `clickhouse-2` picks up the Kafka partitions (`system.kafka_consumers`).

## Work breakdown

| # | Change | Files |
|---|---|---|
| 1 | Edge curation: relabel, filter, rate, rename/aggregate | `otel/otel-collector-config.yaml` |
| 2 | Sink collector config + compose service | `otel/otel-sink-config.yaml`, `docker-compose.yml`, `docker-compose.ha.yml` |
| 3 | Landing tables, MVs, Kafka tables, DLQ | `clickhouse/sink.sql`, `ha/clickhouse/sink_ha.sql`, compose initdb mounts |
| 4 | IB rate + per-node aggregation | `tools/ib_poller.py` + test |
| 5 | Hostlist expansion, exit_code unwrap, skip pending | `tools/slurm_poller.py` + test |
| 6 | `FINAL` on jobs read | `analysis-api/analysis_api/routers/jobs.py` |
| 7 | Local `node-exporter` service for testing | `docker-compose.yml` |
| 8 | Docs | `INSTALL.md` gap #2, `ingest-infra/README.md`, `docs/deployment.md` |

## Open questions

- Final metric mapping table (§1a) — needs real exporter output from the target cluster.
- OCI RoCE: if counters aren't at `/sys/class/infiniband` (test plan §1.3), `ib_poller` input changes; sink side is unaffected as long as the JSON shape holds.
- Redpanda topic retention: must cover the longest planned ClickHouse outage.
