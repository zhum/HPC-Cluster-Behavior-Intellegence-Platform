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
