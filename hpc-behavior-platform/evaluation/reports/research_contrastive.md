# Research Track: Deep Contrastive Embeddings vs. MulTiDR

Phase 8 item 5 -- gated behind evidence. This is NOT wired into the
production pipeline; adoption depends solely on the table below.

| pipeline | ARI | silhouette | davies_bouldin | calinski_harabasz |
|---|---|---|---|---|
| contrastive (InfoNCE) | 0.911 | 0.539 | 0.611 | 141.5 |
| MulTiDR (default) | 1.000 | 0.921 | 0.111 | 20557.6 |

**Verdict: DO NOT ADOPT (MulTiDR remains the default)**
