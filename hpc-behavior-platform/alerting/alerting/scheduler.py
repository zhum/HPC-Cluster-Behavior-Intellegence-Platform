"""Scheduled headless run of the intra pipeline on each cluster, using
last-known-good baselines, pushing |z| >= threshold events to the
`anomalies` table + webhook (Phase 8 item 4).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from analysis_core.inter.pipeline import InterClusterPipeline
from analysis_core.intra.zscores import compute_zscores
from tensor_store.api import TensorRequest, get_tensor

from alerting.baseline_state import BaselineStateStore
from alerting.store import Anomaly, AnomalyStore
from alerting.webhook import send_webhook

Z_THRESHOLD = 3.0


@dataclass
class RunReport:
    new_anomalies: list[Anomaly] = field(default_factory=list)
    clusters_checked: int = 0
    metrics_checked: int = 0
    webhook_delivered: bool | None = None


def run_once(
    tensor_client: Any,
    alert_client: Any,
    start: datetime,
    end: datetime,
    resolution_s: int,
    k: int,
    band: str,
    webhook_url: str | None = None,
    metrics: list[str] | None = None,
    z_threshold: float = Z_THRESHOLD,
    umap_n_neighbors: int = 15,
    random_state: int = 42,
) -> RunReport:
    # use_cache=False: tensor-store's disk cache is keyed on request params
    # (start/end/resolution_s/nodes/metrics) only, not on the underlying
    # data -- a scheduler polling the same rolling-window shape repeatedly
    # (or, as found while testing this, any two calls that happen to share
    # a window) would otherwise silently get back a stale bundle. Staleness
    # here defeats the entire point of alerting.
    bundle = get_tensor(
        TensorRequest(start=start, end=end, resolution_s=resolution_s), client=tensor_client, use_cache=False
    )
    pipeline = InterClusterPipeline(bundle.X)
    labels, _ = pipeline.get_labels(k=k, n_neighbors=min(umap_n_neighbors, max(1, len(bundle.nodes) - 1)), random_state=random_state)

    anomaly_store = AnomalyStore(alert_client)
    baseline_store = BaselineStateStore(alert_client)
    metric_idx = {m: i for i, m in enumerate(bundle.metrics)}
    target_metrics = metrics if metrics is not None else bundle.metrics

    report = RunReport()
    now = datetime.now(timezone.utc)

    for cluster_id in sorted(set(int(label) for label in labels)):
        node_idx = np.where(labels == cluster_id)[0]
        cluster_nodes = [bundle.nodes[i] for i in node_idx]
        report.clusters_checked += 1

        for metric in target_metrics:
            m_i = metric_idx[metric]
            S = bundle.X[node_idx, m_i, :]

            stored_window = baseline_store.get(cluster_id, metric)
            baseline_windows = {metric: stored_window} if stored_window is not None else None

            result = compute_zscores(
                {metric: S}, band=band, resolution_s=resolution_s, baseline_windows=baseline_windows
            )
            report.metrics_checked += 1

            if metric in result.degenerate_metrics:
                continue

            window = result.baseline_windows[metric]
            window_tuple = (window.start, window.stop) if isinstance(window, slice) else window

            z = result.z[:, 0]
            any_anomaly = False
            for i, node_id in enumerate(cluster_nodes):
                if abs(z[i]) < z_threshold:
                    continue
                any_anomaly = True
                if anomaly_store.is_suppressed(node_id, metric, band):
                    continue
                report.new_anomalies.append(
                    Anomaly(
                        id=str(uuid.uuid4()),
                        detected_at=now,
                        cluster_id=cluster_id,
                        node_id=node_id,
                        metric=metric,
                        band=band,
                        z_score=float(z[i]),
                        baseline_window=window_tuple,
                    )
                )

            if not any_anomaly:
                # clean run: safe to adopt this window as the new last-known-good baseline
                baseline_store.set(cluster_id, metric, window_tuple)

    anomaly_store.insert_anomalies(report.new_anomalies)

    if report.new_anomalies and webhook_url:
        payload = {
            "run_at": now.isoformat(),
            "anomalies": [
                {
                    "id": a.id,
                    "cluster_id": a.cluster_id,
                    "node_id": a.node_id,
                    "metric": a.metric,
                    "band": a.band,
                    "z_score": a.z_score,
                }
                for a in report.new_anomalies
            ],
        }
        report.webhook_delivered = send_webhook(webhook_url, payload)

    return report
