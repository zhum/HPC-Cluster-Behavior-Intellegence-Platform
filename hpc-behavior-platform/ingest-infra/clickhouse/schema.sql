-- HPC Behavior Platform: Phase 1 telemetry schema
-- Retention math (documented per README requirement):
--   worst case ingest ~= 10,000 nodes * 500 metrics / 15s ~= 333,333 points/s
--   raw row ~= 8(ts)+~16(node_id LC)+~16(metric LC)+8(value) ~= ~20-30 bytes/row
--     pre-compression; ClickHouse LowCardinality + delta/gorilla codecs typically
--     achieve 5-10x on this shape -> ~3-6 bytes/row effective on disk.
--   333k rows/s * 86400 s/day ~= 28.8B rows/day; at ~4 bytes/row effective
--     ~= ~115 GB/day. On 8 TB usable (~7 TB after overhead), that is roughly
--     60 days at worst-case scale, and well over 90 days at the more typical
--     ~1,000-2,000 node / 100-200 metric analysis-session scale this project
--     targets day-to-day. TTL below is set to 45 days as a conservative default;
--     tune per actual observed compression ratio once real data lands.

CREATE TABLE IF NOT EXISTS metrics_raw
(
    ts      DateTime64(3),
    node_id LowCardinality(String),
    metric  LowCardinality(String),
    value   Float64 CODEC(Gorilla, ZSTD(3))
)
ENGINE = MergeTree
PARTITION BY toDate(ts)
ORDER BY (metric, node_id, ts)
TTL toDateTime(ts) + INTERVAL 45 DAY;

-- 1-minute rollup. count() per (metric,node_id,minute) is how the tensor-store
-- (Phase 2) detects null/downtime segments: count=0 for an expected bucket
-- means no readings arrived for that node in that minute.
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
ENGINE = AggregatingMergeTree
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
ENGINE = ReplacingMergeTree
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
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY node_id;

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
ENGINE = ReplacingMergeTree
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
ENGINE = ReplacingMergeTree
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
ENGINE = ReplacingMergeTree
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
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id, id);
