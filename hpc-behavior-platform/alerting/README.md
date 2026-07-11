# alerting — Phase 8 item 4 (optional, beyond the paper)

Scheduled headless runs of the intra pipeline per cluster, using
last-known-good baselines, pushing `|z| >= threshold` events to ClickHouse's
`anomalies` table plus a webhook. Includes the operator false-positive
feedback loop (dismiss -> suppress rule).

```
alerting/
  scheduler.py       run_once(): tensor -> cluster -> per-metric zscores
                     against the stored baseline -> new anomalies + webhook
  store.py           AnomalyStore: insert/list/dismiss (dismiss also inserts
                     a suppression rule for that node/metric/band)
  baseline_state.py  last-known-good baseline window per (cluster, metric),
                     only updated after a run with no anomaly for that metric
  webhook.py         best-effort POST with retries; a failed delivery never
                     drops the anomaly (already persisted regardless)
  run.py             CLI: --interval-s 0 runs once, >0 loops
```

ClickHouse tables added: `anomalies`, `suppression_rules`, `baseline_state`
(see `ingest-infra/clickhouse/schema.sql`).

Run once: `python -m alerting.run --lookback-s 3600 --band 2h`

## A real bug this caught

`tensor_store.get_tensor`'s disk cache is keyed on request params (start/
end/resolution_s/nodes/metrics) only, not on the underlying data. Two test
runs sharing the same time window got back a stale bundle from whichever
ran first — invisible in one-shot CLI usage, but exactly the failure mode a
polling scheduler would eventually hit for real. Fixed by calling
`get_tensor(..., use_cache=False)` here: staleness in a monitoring pipeline
defeats the entire point of alerting.
