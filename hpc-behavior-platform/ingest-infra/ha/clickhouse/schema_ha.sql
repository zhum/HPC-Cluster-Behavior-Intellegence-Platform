-- HA variant of the Phase 1 schema (Phase 8 item 2): ReplicatedMergeTree
-- instead of MergeTree, and a tiered storage policy for retention.
--
-- Runs independently and identically on every node via docker-entrypoint-
-- initdb.d -- no ON CLUSTER here on purpose: each node creates its own
-- local replica pointing at the same Keeper-coordinated path, which avoids
-- a startup-ordering race where node A's ON CLUSTER DDL fires before node
-- B is listening. The {shard}/{replica} macros come from each node's own
-- macros.xml (see ha/clickhouse/node1, node2).

CREATE TABLE IF NOT EXISTS metrics_raw
(
    ts      DateTime64(3),
    node_id LowCardinality(String),
    metric  LowCardinality(String),
    value   Float64 CODEC(Gorilla, ZSTD(3))
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/metrics_raw', '{replica}')
PARTITION BY toDate(ts)
ORDER BY (metric, node_id, ts)
TTL toDateTime(ts) + INTERVAL 45 DAY TO DISK 's3_cold'
SETTINGS storage_policy = 'tiered';

-- Demo-only: identical shape, but a 30-second TTL-to-s3_cold so the tiering
-- move is observable in a live check without waiting 45 days. Not part of
-- the real retention design -- see metrics_raw above for that.
CREATE TABLE IF NOT EXISTS metrics_raw_demo_tiering
(
    ts      DateTime64(3),
    node_id LowCardinality(String),
    metric  LowCardinality(String),
    value   Float64 CODEC(Gorilla, ZSTD(3))
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/metrics_raw_demo_tiering', '{replica}')
PARTITION BY toDate(ts)
ORDER BY (metric, node_id, ts)
TTL toDateTime(ts) + INTERVAL 30 SECOND TO DISK 's3_cold'
SETTINGS storage_policy = 'tiered';

CREATE TABLE IF NOT EXISTS metrics_1m
(
    ts_bucket DateTime,
    node_id   LowCardinality(String),
    metric    LowCardinality(String),
    avg_state AggregateFunction(avg, Float64),
    min_state AggregateFunction(min, Float64),
    max_state AggregateFunction(max, Float64),
    cnt_state AggregateFunction(count, Float64)
)
ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/metrics_1m', '{replica}')
PARTITION BY toDate(ts_bucket)
ORDER BY (metric, node_id, ts_bucket)
TTL ts_bucket + INTERVAL 365 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1m_mv
TO metrics_1m
AS
SELECT
    toStartOfMinute(ts)   AS ts_bucket,
    node_id,
    metric,
    avgState(value)       AS avg_state,
    minState(value)       AS min_state,
    maxState(value)       AS max_state,
    countState(value)     AS cnt_state
FROM metrics_raw
GROUP BY ts_bucket, node_id, metric;

CREATE TABLE IF NOT EXISTS jobs
(
    job_id     String,
    user       LowCardinality(String),
    partition  LowCardinality(String),
    node_list  Array(String),
    state      LowCardinality(String),
    start_time DateTime,
    end_time   Nullable(DateTime),
    exit_code  Nullable(Int32),
    priority   Nullable(UInt32)
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/jobs', '{replica}')
ORDER BY (start_time, job_id);

CREATE TABLE IF NOT EXISTS node_inventory
(
    node_id      LowCardinality(String),
    rack         LowCardinality(String),
    cabinet      LowCardinality(String),
    cage         LowCardinality(String),
    partition    LowCardinality(String),
    hardware_gen LowCardinality(String),
    updated_at   DateTime DEFAULT now()
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/node_inventory', '{replica}', updated_at)
ORDER BY node_id;

-- Phase 8 items 3-4 tables, replicated (keep in sync with clickhouse/schema.sql).
-- Phase 8 item 4 (alerting, optional/beyond the paper): scheduled headless
-- intra-pipeline runs push |z| >= threshold events here.
CREATE TABLE IF NOT EXISTS anomalies
(
    id                     String,
    detected_at            DateTime64(3),
    cluster_id             Int32,
    node_id                LowCardinality(String),
    metric                 LowCardinality(String),
    band                   LowCardinality(String),
    z_score                Float64,
    baseline_window_start  UInt32,
    baseline_window_end    UInt32,
    status                 LowCardinality(String) DEFAULT 'open',  -- 'open' | 'dismissed'
    dismissed_at           Nullable(DateTime64(3)),
    dismissed_by           Nullable(String),
    dismiss_reason         Nullable(String)
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/anomalies', '{replica}')
ORDER BY (detected_at, id);

-- Operator "dismiss -> suppress" feedback: a (node_id, metric, band) that
-- has been dismissed as a false positive is suppressed from future alerts.
CREATE TABLE IF NOT EXISTS suppression_rules
(
    id         String,
    node_id    LowCardinality(String),
    metric     LowCardinality(String),
    band       LowCardinality(String),
    created_at DateTime64(3),
    created_by Nullable(String),
    reason     Nullable(String)
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/suppression_rules', '{replica}')
ORDER BY (node_id, metric, band, created_at);

-- Last-known-good baseline window per (cluster, metric), so the scheduler
-- doesn't recompute (and potentially drift) the baseline from a run that
-- itself contains an ongoing anomaly -- only updated after a clean run.
CREATE TABLE IF NOT EXISTS baseline_state
(
    cluster_id   Int32,
    metric       LowCardinality(String),
    window_start UInt32,
    window_end   UInt32,
    updated_at   DateTime64(3)
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/baseline_state', '{replica}')
ORDER BY (cluster_id, metric);

-- Phase 8 item 3 (multi-user sessions, optional/beyond the paper): saved
-- analyses persisted per user (baselines, lassoNodeIds, selectedMetrics,
-- band, k, umapParams, annotations -- the full cross-view UI state from
-- behavior-ui's Zustand store, opaque JSON here since analysis-api doesn't
-- need to interpret it, only store/retrieve it per owning user).
-- `deleted` is a soft-delete flag rather than a real DELETE: ClickHouse's
-- ALTER TABLE ... DELETE is an async mutation with no guaranteed immediate
-- visibility to a subsequent SELECT (confirmed live -- a delete followed
-- immediately by a list refresh still showed the "deleted" row). Deleting
-- is instead just another insert of a newer version with deleted=1,
-- riding the same ReplacingMergeTree + FINAL read pattern already used for
-- updates, which -is- synchronously visible.
CREATE TABLE IF NOT EXISTS saved_analyses
(
    id         String,
    user_id    LowCardinality(String),
    name       String,
    state_json String,
    deleted    UInt8 DEFAULT 0,
    created_at DateTime64(3),
    updated_at DateTime64(3)
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/saved_analyses', '{replica}', updated_at)
ORDER BY (user_id, id);
