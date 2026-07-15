# User Guide

For analysts investigating cluster behavior via the `behavior-ui` frontend. Assumes the stack is already running — see [Quick Start](./quick-start.md) if not.

## Mental model

The platform answers two questions in sequence:

1. **Which nodes are behaving similarly to each other, and which stand apart?** (inter-node analysis)
2. **Within a group of nodes I've selected, which specific node/metric/time-window looks anomalous, and how anomalous?** (intra-node analysis)

The four views map directly onto this: Node Similarity answers (1); Time Domain, Metric Reading, and Node Behavior answer (2) for whatever you've selected in Node Similarity.

## Starting a session

Opening the UI creates a session against a time range and resolution. The session materializes the analysis tensor (nodes × metrics × time) from ClickHouse in the background and warms the first dimensionality-reduction stage. Larger time ranges / more nodes take longer to materialize — the UI shows session status while this happens.

Session limits are enforced server-side: **N ≤ 2000 nodes, M ≤ 500 metrics, T ≤ 10000 timesteps.** A request outside these bounds is rejected (HTTP 422) rather than silently degrading — if your query gets rejected, narrow the time range, metric selection, or node scope.

## The four views

### Node Similarity

The entry point. Runs MulTiDR (PCA → UMAP) and k-means over the session's node×time data, plotting nodes in a 2D embedding where proximity indicates similar temporal behavior. Nodes are colored by cluster assignment.

Selecting a cluster here (click or lasso) drives what the other three views show — this is the "which nodes am I looking at" control for the rest of the UI.

Cluster explanations use contrastive PCA (ccPCA): for a selected cluster, it surfaces the metrics that most distinguish that cluster from the rest of the population, not just the metrics with the highest raw variance.

### Time Domain

Shows the raw or aggregated time series for the currently selected cluster/nodes, with job overlays (Slurm job start/end boundaries) so you can correlate behavior changes with job scheduling.

### Metric Reading

Three-part view for drilling into individual metrics within the selected cluster:

- **Metric selection** — choose which metric(s) to inspect.
- **Cluster reading summary** — aggregate statistics for the metric across the cluster.
- **Reading inspection** — per-node detail for the chosen metric.

### Node Behavior

Runs mrDMD (multiresolution Dynamic Mode Decomposition) frequency-band analysis on the selected cluster, computing z-scores per node/metric/band against a statistically-derived baseline. Nodes with `|z| ≥ 3` in a band are flagged as anomalous for that frequency range.

This is where you'd spot, e.g., a node with a slow memory-leak-shaped drift or a burst of InfiniBand errors relative to its cluster peers — though see the note below on DMD's blind spots.

**Known limitation:** DMD models oscillatory/exponential dynamics well. It's a poor fit for monotonic ramps (e.g., a slow memory leak) and struggles with anomalies shorter than the mrDMD window size (e.g., brief IB error bursts). If Node Behavior looks "clean" for a node you suspect is degrading, check Time Domain / Metric Reading directly rather than trusting the absence of a z-score flag — see `evaluation/reports/fault_injection.md` for the measured recall gaps.

## Saved analyses

You can save the current investigation state — baselines, lasso selections, chosen metrics, band, k, UMAP params, i.e. the full UI state — and reload it later via the Saved Analyses panel. Saves are scoped to a `user_id` you supply; there's no login, so this is a convenience for picking up where you left off, not a private workspace (see [Admin Guide § Security posture](./admin-guide.md#security-posture)).

## Reading the alerting output (if enabled)

If an operator has `alerting` running (see [Admin Guide § Alerting](./admin-guide.md#alerting)), new anomalies land as webhook notifications and rows in the `anomalies` table, using the same z-score methodology as the Node Behavior view but run on a schedule rather than on-demand. If you dismiss an alert as expected/noisy, tell your admin — dismissals create suppression rules that need admin-side handling, they're not currently exposed as a UI action.
