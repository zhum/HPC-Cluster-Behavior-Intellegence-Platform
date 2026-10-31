# evaluation — Phase 7: Validation & Evaluation

Makes "meaningful clusters" falsifiable per the v2 spec's Phase 7 gates.

```
evaluation/
  fixtures.py           synthetic planted-cluster tensor (option (a) from spec item 1;
                         (b)/(c) not exercised -- no licensable public dataset available,
                         no week-long real telemetry has been operated in this environment)
  quality_benchmark.py   paper's Table I metrics + Phase 3 gate (ARI>0.9, beats PCA-only)
  dr_ablation.py         PCA-only / UMAP-direct / t-SNE vs default MulTiDR (paper Fig. 9)
  fault_injection.py     cpu_steal / memory_leak_ramp / ib_error_burst / dead_node
                         perturbations + Phase 4 gate (recall>=0.9 at |z|>=3)
  ground_truth.py        precision@k against jobs/incident lists (pure functions,
                         no live ClickHouse dependency)
  research_contrastive.py  Phase 8 item 5 (research track, gated behind evidence):
                         deep contrastive (InfoNCE) node embeddings as an
                         ALTERNATIVE dr1, evaluated against MulTiDR -- NOT wired
                         into the production pipeline. Needs the `research` extra
                         (torch): `pip install -e ".[research]"`.
  run_all.py             regenerates reports/*.md
```

Run `python -m evaluation.run_all` to regenerate the reports.

## Gate results (synthetic planted-cluster data)

- **Phase 3 gate** (ARI > 0.9, beats PCA-only baseline): PASS — MulTiDR ARI 1.000
  vs PCA-only 0.716, UMAP-direct 0.866, t-SNE 0.681.
- **Phase 4 gate** (on every seed 0-9: recall >= 0.9 at \|z\| >= 3, at
  most 10% of healthy nodes flagged): PASS for `cpu_steal`,
  `memory_leak_ramp` and `dead_node`. **Not** met for `ib_error_burst`
  (worst seed: recall 0.25, 12% of healthy nodes flagged). The "5m" band
  only sees a 2-sample impulse through noise-level DMD modes, which span
  all nodes and spill the burst onto healthy ones; no band/max_cycles/window
  or SVD truncation setting gives both full recall and no healthy flags.

See `tests/test_fault_injection.py` for the exact assertions and
`reports/*.md` for the generated tables.

## Research track (Phase 8 item 5, gated behind evidence)

Deep contrastive (InfoNCE) node embeddings, evaluated as an alternative to
dr1 on the same planted-cluster fixture: ARI 0.911 vs MulTiDR's 1.000,
silhouette 0.539 vs 0.921. **Verdict: DO NOT ADOPT** — MulTiDR's explicit
per-metric temporal PCA remains the default. Not wired into
analysis-core's production pipeline; see `research_contrastive.py`.
