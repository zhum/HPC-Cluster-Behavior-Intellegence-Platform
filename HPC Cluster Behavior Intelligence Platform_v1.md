# PROJECT: HPC Cluster Behavior Intelligence Platform

version: 1.0

objective: Implement the methodology described in [arXiv 2604.11965: “Understanding Large-Scale HPC System Behavior Through Cluster-Based Visual Analytics”](https://arxiv.org/abs/2604.11965)

references:
* arxiv:2604.11965
* two_phase_dimensionality_reduction
* contrastive_learning
* multi_resolution_dmd
* cluster_behavior_analysis


summary: Build a production-grade HPC telemetry and analytics platform capable of:
* collecting node telemetry
* generating behavioral feature vectors
* learning node embeddings
* clustering node behavior
* detecting anomalies
* performing temporal behavior analysis using mrDMD
* visualizing inter-cluster and intra-cluster behavior



target_scale:
  nodes: 1000-10000
  metrics_per_node: 100-500
  ingestion_rate: 100k-1M metrics/sec

## PHASE 1 OBSERVABILITY FOUNDATION 

goal: Collect and store all telemetry.

deliverables:
* telemetry ingestion
* centralized storage
* basic dashboards

servers:
  - telemetry_server:
    - cpu: 32
    - ram_gb: 128
    - storage: 2TB NVMe
  - storage_server:
    - cpu: 32
    - ram_gb: 256
    - storage: 8TB NVMe

software_install:

  - telemetry_server:
    - OpenTelemetry Collector
    - Redpanda
  - storage_server:
    - ClickHouse
    - MinIO
    - Grafana

redpanda_topics:
* otel.metrics
* otel.logs
* otel.events
* slurm.jobs
* gpu.metrics
* infiniband.metrics

clickhouse_tables:

- metrics_raw
- metrics_1m
- metrics_5m
- jobs
- node_inventory
- anomalies

telemetry_metrics:

  - cpu:
    * utilization
    * load_avg
    * context_switches
    * interrupts

  - memory:
    * used
    * free
    * page_faults
    * swap

  - network:
    * tx_bytes
    * rx_bytes
    * drops
    * retransmits

  - storage:
    * iops
    * throughput
    * latency

  - gpu:
    * utilization
    * memory_used
    * power
    * temperature
    * ecc_errors
    * nvlink_tx
    * nvlink_rx

  - infiniband:
    * retries
    * congestion
    * symbol_errors
    * link_downed

  - slurm:
    * job_id
    * user
    * partition
    * nodes
    * state

  - repositories:
    * observability-agent

repository_structure:

observability-agent/
  agent/
     collectors/
       cpu.py
       memory.py
       network.py
       storage.py
       gpu.py
       infiniband.py
       slurm.py
     exporters/
       otlp.py
     config/
       main.py

python_packages:
* opentelemetry-sdk
* opentelemetry-exporter-otlp
* psutil
* pynvml
* pyyaml

milestone:
  metrics visible in Grafana

## PHASE 2 FEATURE ENGINEERING

goal: Convert raw telemetry into behavioral vectors.

new_server:

feature_server:
  - cpu: 32
  - ram_gb: 128

software_install:
  * Apache Flink

repository:
  feature-pipeline

repository_structure:

feature-pipeline/
  feature_pipeline/
  windows/
  aggregations/
  transforms/
  schemas/
  writers/
  main.py

window_sizes:
* 1m
* 5m
* 15m
* 60m

feature_generation:

for_each_metric:

statistics:
- mean
- std
- median
- min
- max
- p95
- p99
temporal:
- slope
- derivative
- variance
frequency:
- fft_energy
- dominant_frequency

output_table:

feature_vectors

schema:

node_id timestamp window_size

feature_*

target_feature_count: 500-2000

milestone:

stable feature vectors generated continuously

## PHASE 3 CLUSTER DISCOVERY

goal: Reproduce inter-cluster analysis.

new server:

analytics_server:
- cpu: 64
- ram_gb: 256

repository:

behavior-analytics

repository_structure:

behavior-analytics/
  analytics/
    pca/
    umap/
    clustering/
    explainability/
    jobs/
    main.py

python_packages:
* numpy
* pandas
* scikit-learn
* umap-learn
* hdbscan
* clickhouse-connect

pipeline:

step_1: incremental_pca

input_dimensions: 500-2000

output_dimensions: 64

step_2: umap

output_dimensions: 2

step_3: hdbscan

outputs:

cluster_assignments cluster_confidence

clickhouse_tables:

embeddings_pca umap_coordinates node_clusters

milestone:

nodes grouped by behavior

## PHASE 4 CONTRASTIVE EMBEDDINGS

goal: Learn latent behavior representation.

new server:

training_server:

gpu: vram 32G+
ram_gb: 128

repository:

behavior-embedding

repository_structure:

behavior-embedding/
  datasets/
  models/
  losses/
  training/
  inference/
  export/

model:

encoder:

input: 512
layers:
  - 256
  - 128
  - 64
  - 32
output: 32

loss:

InfoNCE

positive_pairs:
* same_node_adjacent_windows
* same_job_adjacent_windows

negative_pairs:
* different_cluster
* different_partition

python_packages:
* torch
* torchvision
* lightning
* onnx
* onnxruntime

artifacts:

encoder.pt encoder.onnx

serving_repository:

embedding-service

repository_structure:

embedding-service/
  api/
  inference/
  models/

serving_stack:
* FastAPI
* ONNX Runtime

endpoint:

POST /embed

milestone:

online embedding generation

## PHASE 5 mrDMD ANALYSIS

goal: Reproduce intra-cluster analysis.

repository:

temporal-analysis

repository_structure:

temporal-analysis/
  mrdmd/
  baselines/
  zscores/
  anomaly_scoring/
  main.py

python_packages:
* pydmd
* numpy
* scipy

frequency_levels:
* 5m
* 30m
* 2h
* 24h
* 7d

pipeline:

1: load_cluster_embeddings
2: compute_mrdmd_modes
3: detect_stable_intervals
4: compute_baseline
5: compute_z_scores

outputs:

node_behavior_scores anomaly_scores

clickhouse_tables:

mrdmd_modes mrdmd_zscores node_anomalies

milestone:

temporal anomaly detection operational

## PHASE 6 UI PLATFORM

goal: Reproduce paper-style visual analytics interface.

backend_repository:

cluster-behavior-api

stack:
* FastAPI
* Redis
* ClickHouse

modules:

nodes clusters anomalies jobs embeddings temporal

frontend_repository:

cluster-behavior-ui

stack:
* React
* TypeScript
* DeckGL
* D3
* MaterialUI

views:

cluster_view: description: UMAP node map

cluster_explanation: description: discriminative metrics

temporal_view: description: mrDMD modes

anomaly_heatmap: description: node metric anomaly matrix

node_details: description: raw telemetry and embeddings

milestone:

complete interactive analytics system

## DEVOPS

infrastructure_as_code:

repositories:

terraform/
ansible/
helm/

deployment:

kubernetes: optional

ci_cd: github_actions

environments:
- dev
- stage
- prod

## FINAL PRODUCTION DATA FLOW

- Compute Node
- OpenTelemetry Collector
- Redpanda
- ClickHouse
- Feature Pipeline
- PCA
- Contrastive Encoder
- HDBSCAN
- mrDMD
- Anomaly Engine
- FastAPI
- React UI

## SUCCESS CRITERIA

phase1: telemetry visible

phase2: behavioral vectors generated

phase3: meaningful node clusters discovered

phase4: latent embeddings operational

phase5: temporal anomalies detected

phase6: operators can visually explore: - cluster differences - node similarities - anomalous nodes - temporal behavior evolution

