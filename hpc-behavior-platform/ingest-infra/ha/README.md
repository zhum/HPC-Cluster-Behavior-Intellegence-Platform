# HA infra + retention tiering (Phase 8 item 2, optional/beyond the paper)

Standalone overlay -- does not touch the base `docker-compose.yml` dev
stack every earlier phase depends on. Run with:

```
docker compose -f docker-compose.ha.yml up -d
```

## What's in it

- **3-node ClickHouse Keeper quorum** (`clickhouse-keeper-1/2/3`) -- a
  single keeper node would itself be a single point of failure, defeating
  the point of "HA".
- **2 ClickHouse replicas** (`clickhouse-1`, `clickhouse-2`) of the same
  shard, using `ReplicatedMergeTree`/`ReplicatedReplacingMergeTree`/
  `ReplicatedAggregatingMergeTree` (see `clickhouse/schema_ha.sql`).
- **3-broker Redpanda cluster** (`redpanda-1/2/3`), topics created with
  replication factor 3.
- **MinIO** as the S3-compatible cold-storage tier, with a ClickHouse
  storage policy (`clickhouse/common/storage.xml`) that moves `metrics_raw`
  parts older than 45 days there instead of deleting them (`TTL ... TO DISK
  's3_cold'`) -- extends the plain-delete TTL used in the base dev stack's
  schema.

`metrics_raw_demo_tiering` is a demo-only table with a 30-second TTL (same
shape, same policy) so the move is observable in a live check without
waiting 45 days. It is not part of the real retention design.

## Verifying it

Run `./ha/verify.sh` after bringing the stack up (checks replication, Redpanda
cluster health/replication-factor, and retention tiering; exits non-zero on
the first failed check; takes ~40s due to waiting out the demo table's TTL).

## Verified live (ports differ from the base dev stack to avoid collisions)

```bash
# replication: insert on node1 (8124), read from node2 (8125)
curl -u default:devpass "http://localhost:8124/" --data-binary \
  "INSERT INTO metrics_raw (ts, node_id, metric, value) VALUES (now64(3), 'x', 'y', 1.0)"
curl -u default:devpass "http://localhost:8125/?query=SELECT count() FROM metrics_raw WHERE node_id='x'"

# redpanda cluster health
docker exec ingest-infra-redpanda-1-1 rpk cluster health

# retention tiering: after the demo table's parts age past 30s,
# OPTIMIZE forces the TTL check instead of waiting for a background merge
curl -u default:devpass "http://localhost:8124/" --data-binary \
  "OPTIMIZE TABLE metrics_raw_demo_tiering FINAL"
curl -u default:devpass "http://localhost:8124/?query=SELECT disk_name, count() FROM system.parts WHERE table='metrics_raw_demo_tiering' AND active GROUP BY disk_name"
# -> s3_cold, confirmed via both ClickHouse system.parts and directly
#    listing objects in the MinIO bucket (mc ls local/clickhouse-cold/)
```

Results at time of writing: replication propagated within ~3s; Redpanda
reported `Healthy: true`, all 3 topics at replication factor 3, 0
under-replicated partitions; the demo table's part moved from `default` to
`s3_cold` on both replicas after the TTL check, with matching objects
visible in the MinIO bucket.

## Known rough edges hit while building this

- ClickHouse Keeper's healthcheck needs `four_letter_word_allow_list`
  explicitly enabled (disabled by default) before `ruok` works at all.
- Inside the keeper container, `localhost` resolves to `::1` first but
  Keeper only listens on IPv4 -- healthchecks must target `127.0.0.1`
  explicitly.
- `TTL <column> TO DISK` requires a `DateTime`/`Date` expression, not
  `DateTime64` directly -- wrap with `toDateTime(...)`, same as the base
  schema's delete-TTL already does.
- `ReplicatedReplacingMergeTree` takes `(zookeeper_path, replica_name,
  ver_column)` -- easy to accidentally drop the replica_name argument when
  adding the version column.
- initdb scripts run independently per node with no cross-node
  coordination; deliberately not using `ON CLUSTER` DDL here to avoid a
  startup-ordering race (node A's DDL firing before node B is listening).
