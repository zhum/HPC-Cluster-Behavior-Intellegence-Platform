# Cluster Quality Benchmark

Generated: 2026-07-11T17:24:02.796506+00:00

| dataset | N | M | T | ARI (MulTiDR) | ARI (PCA-only) | silhouette | davies_bouldin | calinski_harabasz | trustworthiness | continuity | gate: ARI>0.9 | gate: beats PCA-only |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| synthetic_planted | 60 | 8 | 60 | 1.000 | 0.716 | 0.921 | 0.111 | 20557.6 | 0.978 | 0.978 | PASS | PASS |

## PCA-only baseline detail (for comparison)

| dataset | silhouette | davies_bouldin | calinski_harabasz |
|---|---|---|---|
| synthetic_planted | 0.515 | 0.624 | 100.2 |
