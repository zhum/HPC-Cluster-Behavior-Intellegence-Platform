#!/usr/bin/env bash
# Live verification of the Phase 8 item 2 HA overlay (replication, Redpanda
# cluster health, retention tiering). Assumes docker-compose.ha.yml is
# already up:
#
#   docker compose -f docker-compose.ha.yml up -d
#   ./ha/verify.sh
#
# Exits non-zero on the first failed check.
set -euo pipefail

CH1="http://localhost:8124"
CH2="http://localhost:8125"
AUTH="default:devpass"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; exit 1; }

echo "--- 1. ClickHouse replication ---"
NODE_ID="ha-verify-$(date +%s)"
curl -s -u "$AUTH" "$CH1/" --data-binary \
  "INSERT INTO metrics_raw (ts, node_id, metric, value) VALUES (now64(3), '$NODE_ID', 'verify.metric', 42.0)" \
  > /dev/null

REPLICATED=0
for _ in $(seq 1 10); do
  COUNT=$(curl -s -u "$AUTH" "$CH2/?query=SELECT+count()+FROM+metrics_raw+WHERE+node_id='$NODE_ID'+FORMAT+TSV")
  if [ "$COUNT" = "1" ]; then
    REPLICATED=1
    break
  fi
  sleep 1
done
[ "$REPLICATED" = "1" ] && pass "insert on node1 (8124) visible on node2 (8125)" \
  || fail "row not replicated to node2 within 10s"

echo "--- 2. Redpanda cluster health ---"
HEALTH=$(docker exec ingest-infra-redpanda-1-1 rpk cluster health 2>&1)
echo "$HEALTH" | grep -q "Healthy:.*true" && pass "redpanda cluster reports healthy" \
  || fail "redpanda cluster unhealthy:\n$HEALTH"

for topic in otel.metrics slurm.jobs ib.metrics; do
  REPLICAS=$(docker exec ingest-infra-redpanda-1-1 rpk topic describe "$topic" 2>&1 | awk '/^REPLICAS/{print $2}')
  [ "$REPLICAS" = "3" ] && pass "$topic replication factor 3" \
    || fail "$topic replication factor is '$REPLICAS', expected 3"
done

echo "--- 3. Retention tiering (demo table, 30s TTL) ---"
curl -s -u "$AUTH" "$CH1/" --data-binary \
  "INSERT INTO metrics_raw_demo_tiering (ts, node_id, metric, value) VALUES (now64(3), 'tier-verify', 'tier.test', 1.0)" \
  > /dev/null

echo "waiting 35s for the demo TTL to age past..."
sleep 35
curl -s -u "$AUTH" "$CH1/" --data-binary "OPTIMIZE TABLE metrics_raw_demo_tiering FINAL" > /dev/null

MOVED=0
for _ in $(seq 1 10); do
  DISKS=$(curl -s -u "$AUTH" "$CH1/?query=SELECT+disk_name+FROM+system.parts+WHERE+table='metrics_raw_demo_tiering'+AND+active+FORMAT+TSV")
  if echo "$DISKS" | grep -q "s3_cold"; then
    MOVED=1
    break
  fi
  sleep 2
done
[ "$MOVED" = "1" ] && pass "metrics_raw_demo_tiering part moved to s3_cold" \
  || fail "no part on s3_cold disk after TTL + OPTIMIZE FINAL (got: $DISKS)"

DISKS2=$(curl -s -u "$AUTH" "$CH2/?query=SELECT+disk_name+FROM+system.parts+WHERE+table='metrics_raw_demo_tiering'+AND+active+FORMAT+TSV")
echo "$DISKS2" | grep -q "s3_cold" && pass "tiered part also visible as s3_cold on replica node2" \
  || fail "replica node2 does not show the part on s3_cold (got: $DISKS2)"

echo
echo "ALL CHECKS PASSED"
