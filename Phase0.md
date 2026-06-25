# PHASE 0 DATA VALIDATION AND TELEMETRY QUALITY FRAMEWORK

goal:
Ensure all telemetry entering the analytics pipeline is:
- complete
- correctly timestamped
- normalized
- quality-scored
- correlated with cluster state

Prevent machine learning models from learning:
- missing data patterns
- maintenance windows
- node reboots
- scheduler artifacts
- firmware upgrades
- collector failures

duration:
2-4 weeks

## INFRASTRUCTURE
==============

server:

validation_server:
- cpu: 16
- ram_gb: 64
- storage: 1TB NVMe

software_install:
* ClickHouse
* Grafana
* Redis

## REPOSITORIES

repository: telemetry-quality

repository_structure:

telemetry-quality/
  validators/
    completeness.py
    timestamps.py
    normalization.py
    outliers.py
  enrichment/
    slurm_state.py
    maintenance.py
    node_inventory.py
  scoring/
    quality_score.py
  dashboards/
  tests/
  main.py

## NEW DATABASE TABLES

clickhouse_tables:

- node_inventory
- telemetry_quality
- node_state
- maintenance_windows
- collector_health
- metric_dictionary

## NODE INVENTORY DATABASE

purpose: Maintain authoritative metadata for every node.

schema:
- node_id
- hostname
- hardware_generation
- cpu_model
- cpu_cores
- memory_gb
- gpu_model
- gpu_count
- infiniband_hca
- rack
- cluster
- purchase_date
- firmware_version

example:

node001:
- cpu: AMD EPYC 9654
- memory: 512GB
- gpu: H100
- rack: R12

## METRIC DICTIONARY

purpose: Define expected telemetry schema.

schema:

metric_name
- unit
- minimum
- maximum
- collection_interval

examples:

cpu_utilization:
- unit: percent
- minimum: 0
- maximum: 100

gpu_temperature:
- unit: celsius
- minimum: 0
- maximum: 120

## COLLECTOR HEALTH MONITORING

purpose: Detect telemetry collection failures.

metrics:
- collector_heartbeat
- metrics_per_minute
- export_errors
- collection_latency

rules:

if no heartbeat for 5 minutes: collector_state = FAILED

if metric_count drops > 80 percent: generate warning

output_table:
- collector_health

## TIMESTAMP VALIDATION

purpose: Detect clock drift.

checks:
- future_timestamp
- stale_timestamp
- duplicate_timestamp
- non_monotonic_timestamp

thresholds:
maximum_clock_drift_seconds: 30

actions:
- flag
- record
- exclude from training

## COMPLETENESS VALIDATION

purpose: Ensure expected metrics are present.

checks:
- issing_metric
- partial_window
- incomplete_node

examples:

expected_metrics: 120
received_metrics: 95
completeness_score: 79.1

output: completeness_score

## RANGE VALIDATION

purpose: Detect impossible values.

checks:
- cpu_utilization > 100
- memory_used > memory_total
- negative_network_bytes
- gpu_temperature > 120

actions:
- quarantine metric
- record incident

## NORMALIZATION FRAMEWORK

purpose: Normalize hardware differences.

problem:

H100 node and A100 node behave differently.

AMD node and Intel node behave differently.

solution:

create hardware-aware normalization.

methods:
- zscore_per_hardware_type
- percentile_scaling
- robust_scaler

examples:

normalize: cpu_utilization

grouped_by: cpu_model

## NODE STATE ENRICHMENT

purpose: Attach operational context.

sources:
- Slurm
- CMDB
- maintenance database

node_states:
- ACTIVE
- DRAIN
- DOWN
- MAINTENANCE
- ALLOCATED
- IDLE
- REBOOTING

pipeline:

telemetry + node_state -> enriched_telemetry

## MAINTENANCE WINDOW TRACKING

purpose: Prevent false anomalies.

schema:
- node
- start_time
- end_time
- reason

examples:

firmware_update
- kernel_upgrade
- gpu_replacement
- ib_fabric_maintenance

rules:

maintenance telemetry: exclude_from_training = true

## REBOOT DETECTION

purpose: Detect node lifecycle events.

signals:
- uptime reset
- collector restart
- slurm state transition

events:
- NODE_REBOOT
- NODE_REIMAGE
- NODE_RECOVERY

actions:
- suppress anomaly generation

## QUALITY SCORE

purpose: Compute single quality score per node/window.

components:

completeness: weight: 0.35
timestamp_validity: weight: 0.20
collector_health: weight: 0.20
range_validity: weight: 0.15
node_state_validity: weight: 0.10
formula: weighted sum

quality_score: 0-100

thresholds:
- >= 95: training_allowed
- >= 85: inference_allowed
- < 85: inference_flagged
- < 70: exclude_from_pipeline

## TRAINING DATA FILTER

purpose: Ensure only high-quality data reaches ML.

requirements:
- quality_score >= 95
- node_state == ACTIVE
- not maintenance_window
- not reboot_event
- complete feature vector

output:

clean_training_dataset

## DATASET VERSIONING

purpose: Reproduce experiments.

repository:

feature-store

tables:
- dataset_versions

schema:
- dataset_id
- creation_time
- source_window
- quality_threshold
- feature_count

example:

dataset_v0001
dataset_v0002

## GRAFANA DASHBOARDS

dashboard_1: telemetry_quality_overview
  widgets:
    - quality_score_distribution
    - missing_metrics
    - collector_failures

dashboard_2: node_health
  widgets:
    - node_states
    - maintenance_nodes
    - reboot_events

dashboard_3: data_readiness
  widgets:
  - training_eligible_nodes
  - excluded_nodes
  - quality_trend

## SUCCESS CRITERIA

success_conditions:
- > 95 percent telemetry completeness
- < 1 percent invalid timestamps
- collector availability > 99.9 percent
- maintenance windows correctly identified
- node states correctly enriched
- quality score generated for every window

deliverable: trusted telemetry pipeline

exit_condition:

ML phases may begin only after:
quality_score coverage >= 95 percent
and
training_eligible_nodes >= 90 percent

