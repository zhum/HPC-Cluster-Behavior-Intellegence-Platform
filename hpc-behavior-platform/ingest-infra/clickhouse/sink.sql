-- Redpanda -> ClickHouse sink (docs/design-redpanda-clickhouse-sink.md).
-- Runs after schema.sql (docker-entrypoint-initdb.d order is alphabetical).
-- HA variant: ha/clickhouse/sink_ha.sql -- keep the two in sync.

-- ---------------------------------------------------------------------------
-- 1. otel.metrics: the otel-sink collector (otel/otel-sink-config.yaml) reads
--    the topic and its clickhouse exporter inserts into these tables.
--    ENGINE = Null: rows only feed the MVs below, nothing is stored.
--    Columns generated from otel/opentelemetry-collector-contrib:0.104.0 with
--    create_schema: true (codecs/indexes dropped). Bumping the collector image
--    means regenerating them: SHOW CREATE TABLE on a scratch database.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS otel_metrics_gauge
(
    `ResourceAttributes` Map(LowCardinality(String), String),
    `ResourceSchemaUrl` String,
    `ScopeName` String,
    `ScopeVersion` String,
    `ScopeAttributes` Map(LowCardinality(String), String),
    `ScopeDroppedAttrCount` UInt32,
    `ScopeSchemaUrl` String,
    `ServiceName` LowCardinality(String),
    `MetricName` String,
    `MetricDescription` String,
    `MetricUnit` String,
    `Attributes` Map(LowCardinality(String), String),
    `StartTimeUnix` DateTime64(9),
    `TimeUnix` DateTime64(9),
    `Value` Float64,
    `Flags` UInt32,
    `Exemplars.FilteredAttributes` Array(Map(LowCardinality(String), String)),
    `Exemplars.TimeUnix` Array(DateTime64(9)),
    `Exemplars.Value` Array(Float64),
    `Exemplars.SpanId` Array(String),
    `Exemplars.TraceId` Array(String)
)
ENGINE = Null;

CREATE TABLE IF NOT EXISTS otel_metrics_sum
(
    `ResourceAttributes` Map(LowCardinality(String), String),
    `ResourceSchemaUrl` String,
    `ScopeName` String,
    `ScopeVersion` String,
    `ScopeAttributes` Map(LowCardinality(String), String),
    `ScopeDroppedAttrCount` UInt32,
    `ScopeSchemaUrl` String,
    `ServiceName` LowCardinality(String),
    `MetricName` String,
    `MetricDescription` String,
    `MetricUnit` String,
    `Attributes` Map(LowCardinality(String), String),
    `StartTimeUnix` DateTime64(9),
    `TimeUnix` DateTime64(9),
    `Value` Float64,
    `Flags` UInt32,
    `Exemplars.FilteredAttributes` Array(Map(LowCardinality(String), String)),
    `Exemplars.TimeUnix` Array(DateTime64(9)),
    `Exemplars.Value` Array(Float64),
    `Exemplars.SpanId` Array(String),
    `Exemplars.TraceId` Array(String),
    `AggregationTemporality` Int32,
    `IsMonotonic` Bool
)
ENGINE = Null;

CREATE TABLE IF NOT EXISTS otel_metrics_histogram
(
    `ResourceAttributes` Map(LowCardinality(String), String),
    `ResourceSchemaUrl` String,
    `ScopeName` String,
    `ScopeVersion` String,
    `ScopeAttributes` Map(LowCardinality(String), String),
    `ScopeDroppedAttrCount` UInt32,
    `ScopeSchemaUrl` String,
    `ServiceName` LowCardinality(String),
    `MetricName` String,
    `MetricDescription` String,
    `MetricUnit` String,
    `Attributes` Map(LowCardinality(String), String),
    `StartTimeUnix` DateTime64(9),
    `TimeUnix` DateTime64(9),
    `Count` UInt64,
    `Sum` Float64,
    `BucketCounts` Array(UInt64),
    `ExplicitBounds` Array(Float64),
    `Exemplars.FilteredAttributes` Array(Map(LowCardinality(String), String)),
    `Exemplars.TimeUnix` Array(DateTime64(9)),
    `Exemplars.Value` Array(Float64),
    `Exemplars.SpanId` Array(String),
    `Exemplars.TraceId` Array(String),
    `Flags` UInt32,
    `Min` Float64,
    `Max` Float64,
    `AggregationTemporality` Int32
)
ENGINE = Null;

CREATE TABLE IF NOT EXISTS otel_metrics_summary
(
    `ResourceAttributes` Map(LowCardinality(String), String),
    `ResourceSchemaUrl` String,
    `ScopeName` String,
    `ScopeVersion` String,
    `ScopeAttributes` Map(LowCardinality(String), String),
    `ScopeDroppedAttrCount` UInt32,
    `ScopeSchemaUrl` String,
    `ServiceName` LowCardinality(String),
    `MetricName` String,
    `MetricDescription` String,
    `MetricUnit` String,
    `Attributes` Map(LowCardinality(String), String),
    `StartTimeUnix` DateTime64(9),
    `TimeUnix` DateTime64(9),
    `Count` UInt64,
    `Sum` Float64,
    `ValueAtQuantiles.Quantile` Array(Float64),
    `ValueAtQuantiles.Value` Array(Float64),
    `Flags` UInt32
)
ENGINE = Null;

CREATE TABLE IF NOT EXISTS otel_metrics_exponential_histogram
(
    `ResourceAttributes` Map(LowCardinality(String), String),
    `ResourceSchemaUrl` String,
    `ScopeName` String,
    `ScopeVersion` String,
    `ScopeAttributes` Map(LowCardinality(String), String),
    `ScopeDroppedAttrCount` UInt32,
    `ScopeSchemaUrl` String,
    `ServiceName` LowCardinality(String),
    `MetricName` String,
    `MetricDescription` String,
    `MetricUnit` String,
    `Attributes` Map(LowCardinality(String), String),
    `StartTimeUnix` DateTime64(9),
    `TimeUnix` DateTime64(9),
    `Count` UInt64,
    `Sum` Float64,
    `Scale` Int32,
    `ZeroCount` UInt64,
    `PositiveOffset` Int32,
    `PositiveBucketCounts` Array(UInt64),
    `NegativeOffset` Int32,
    `NegativeBucketCounts` Array(UInt64),
    `Exemplars.FilteredAttributes` Array(Map(LowCardinality(String), String)),
    `Exemplars.TimeUnix` Array(DateTime64(9)),
    `Exemplars.Value` Array(Float64),
    `Exemplars.SpanId` Array(String),
    `Exemplars.TraceId` Array(String),
    `Flags` UInt32,
    `Min` Float64,
    `Max` Float64,
    `AggregationTemporality` Int32
)
ENGINE = Null;

-- The edge collector has already curated names, converted counters to rates
-- and aggregated down to a single `node_id` attribute.
CREATE MATERIALIZED VIEW IF NOT EXISTS otel_gauge_to_raw_mv TO metrics_raw AS
SELECT toDateTime64(TimeUnix, 3) AS ts,
       Attributes['node_id']    AS node_id,
       MetricName               AS metric,
       Value                    AS value
FROM otel_metrics_gauge
WHERE node_id != '' AND isFinite(value);

-- deltatorate emits gauges; this catches a counter that slipped past curation
-- so it lands visibly instead of vanishing.
CREATE MATERIALIZED VIEW IF NOT EXISTS otel_sum_to_raw_mv TO metrics_raw AS
SELECT toDateTime64(TimeUnix, 3) AS ts,
       Attributes['node_id']    AS node_id,
       MetricName               AS metric,
       Value                    AS value
FROM otel_metrics_sum
WHERE node_id != '' AND isFinite(value);

-- ---------------------------------------------------------------------------
-- 2. ib.metrics (tools/ib_poller.py): flat JSON, read by the Kafka engine.
--    `ts` is ISO-8601 with offset, so it lands as String and is parsed here.
-- ---------------------------------------------------------------------------

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

-- ---------------------------------------------------------------------------
-- 3. slurm.jobs (tools/slurm_poller.py): times are unix seconds, end_time
--    null/0 while running. Pending jobs are never published (see poller).
-- ---------------------------------------------------------------------------

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
       toDateTime(start_time)                                   AS start_time,
       if(end_time > 0, toDateTime(assumeNotNull(end_time)), NULL) AS end_time,
       exit_code, priority
FROM slurm_jobs_queue
WHERE length(_error) = 0 AND start_time > 0;

-- ---------------------------------------------------------------------------
-- 4. Dead letters: messages the Kafka engine could not parse.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sink_errors
(
    at    DateTime DEFAULT now(),
    topic LowCardinality(String),
    error String,
    raw   String
)
ENGINE = MergeTree
ORDER BY at
TTL at + INTERVAL 7 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ib_errors_mv TO sink_errors AS
SELECT _topic AS topic, _error AS error, _raw_message AS raw
FROM ib_metrics_queue
WHERE length(_error) > 0;

CREATE MATERIALIZED VIEW IF NOT EXISTS slurm_errors_mv TO sink_errors AS
SELECT _topic AS topic, _error AS error, _raw_message AS raw
FROM slurm_jobs_queue
WHERE length(_error) > 0;
