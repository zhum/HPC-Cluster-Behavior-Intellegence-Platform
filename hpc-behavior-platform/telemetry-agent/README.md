# telemetry-agent — node-side collection config (thin)

Per-node setup is standard exporters, no custom code:

- `node_exporter` (CPU, memory, network, disk, load) — scraped by the OTel
  Collector `prometheus` receiver, see `ingest-infra/otel/otel-collector-config.yaml`.
- `dcgm-exporter` (GPU util, memory, power, temp, ECC, NVLink) — same scrape path.
- `ib_poller.py` (`ingest-infra/tools/ib_poller.py`) runs once per IB-equipped
  node, publishing directly to Redpanda `ib.metrics`.
- `chrony`/NTP required on all nodes for clock sync (tensor builder in Phase 2
  aligns to a 15s grid; sub-second skew is tolerated, more than that is not).

## configs/

- `node_exporter.service` — example systemd unit (deploy via Ansible in Phase 8).
- `dcgm_exporter.service` — example systemd unit.
- `ib_poller.service` — example systemd unit, `NODE_ID` and `KAFKA_BROKERS` env
  vars set per host.

No Python collector code lives in this repo (v1's `agent/collectors/*.py` was
scrapped in v2 — see corrected plan item #1: use standard exporters).
