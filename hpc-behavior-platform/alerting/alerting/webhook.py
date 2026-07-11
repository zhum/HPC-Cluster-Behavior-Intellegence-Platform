"""Webhook delivery for newly-detected (non-suppressed) anomalies."""
from __future__ import annotations

import time
from typing import Any

import requests


def send_webhook(url: str, payload: dict[str, Any], timeout: float = 5.0, retries: int = 2) -> bool:
    """Best-effort POST with a couple of retries. Returns whether delivery
    succeeded; the scheduler logs but does not crash on failure -- a
    dropped webhook shouldn't lose the anomaly, which is already persisted
    in ClickHouse regardless of delivery outcome.
    """
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code < 300:
                return True
            last_error = RuntimeError(f"webhook returned {resp.status_code}")
        except requests.RequestException as e:  # noqa: PERF203 -- retry loop, not a hot path
            last_error = e
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    if last_error is not None:
        print(f"[alerting] webhook delivery failed after {retries + 1} attempts: {last_error}")
    return False
