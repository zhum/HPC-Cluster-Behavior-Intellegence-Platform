# Overview

## What this is

An implementation of [arXiv:2604.11965](https://arxiv.org/abs/2604.11965), "Understanding Large-Scale HPC System Behavior Through Cluster-Based Visual Analytics," as a production service.

It ingests per-node HPC telemetry (CPU, memory, network, disk, GPU, InfiniBand, Slurm jobs), materializes it into a dense analysis tensor, and runs a two-phase pipeline:

1. **Inter-node analysis** — dimensionality reduction (MulTiDR: PCA + UMAP) and k-means clustering to find groups of nodes with similar temporal behavior, explained via contrastive PCA (ccPCA).
2. **Intra-node analysis** — multiresolution DMD (mrDMD) frequency-band z-scores against a statistically-derived baseline, to flag anomalous nodes within a chosen cluster.

Results are presented through a four-view coordinated UI (Time Domain, Node Similarity, Metric Reading, Node Behavior) replicating the paper's Figures 2 and 3.

The core pipeline is **classical ML** — PCA, UMAP, k-means, contrastive PCA, DMD — not deep learning.

## Architecture

```
Nodes (Slurm jobs, DCGM GPUs, InfiniBand, node_exporter)
        │  OpenTelemetry
        ▼
telemetry-agent  ──────────►  ingest-infra
(collector config,             (Redpanda → ClickHouse, OTel Collector,
 systemd units)                 Grafana, Redis, optional HA overlay)
                                        │
                                        ▼
                                 tensor-store
                          (materializes N×M×T tensor from ClickHouse)
                                        │
                                        ▼
                                 analysis-core
                    (MulTiDR, k-means, ccPCA, mrDMD, baselines, z-scores)
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                            ▼
                    analysis-api                   alerting
              (FastAPI + Redis cache,        (scheduled headless
               session/saved-analyses)        anomaly scan + webhooks)
                          │
                          ▼
                     behavior-ui
          (React + D3, 4 coordinated views, Zustand state)
```

Supporting package: `evaluation/` — cluster-quality benchmarks, fault injection, DR ablation, ground-truth cross-check. Not part of the runtime path; used to validate the pipeline meets the paper's quality gates.

## Package map

| Package | Phase | Purpose |
|---|---|---|
| `telemetry-agent/` | 1 | Node-side OTel collector config, systemd unit examples |
| `ingest-infra/` | 1 | Docker Compose stack: Redpanda, ClickHouse, OTel Collector, Grafana, Redis; optional HA overlay |
| `tensor-store/` | 2 | Python library materializing the N×M×T tensor from ClickHouse |
| `analysis-core/` | 3–4 | Pure-function analysis library (MulTiDR, k-means, ccPCA, mrDMD, baselines, z-scores) |
| `analysis-api/` | 5 | FastAPI + Redis service exposing analysis-core/tensor-store over HTTP |
| `behavior-ui/` | 6 | React 19 + TypeScript + Vite frontend, 4 coordinated views |
| `evaluation/` | 7 | Cluster-quality benchmarks, fault injection, DR ablation |
| `alerting/` | 8 | Scheduled headless anomaly detection + webhooks (beyond the paper) |

Each Python package is independently versioned with its own `pyproject.toml`, `.venv/`, and `tests/`.

## Where to go next

- New to the project, want it running: [Quick Start](./quick-start.md)
- Setting up dev/prod infra, HA, or real hardware: [Deployment Options](./deployment.md)
- Contributing code, running tests, package conventions: [Development Guide](./development.md)
- Using the UI to investigate cluster behavior: [User Guide](./user-guide.md)
- Operating the stack — auth gaps, retention, alerting, sizing: [Admin Guide](./admin-guide.md)
