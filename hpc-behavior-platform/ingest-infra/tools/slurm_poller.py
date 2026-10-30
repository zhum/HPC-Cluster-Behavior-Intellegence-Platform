"""Poll slurmrestd every 30s and publish job state to Redpanda topic `slurm.jobs`.

The only permitted "custom collector" besides ib_poller.py (see v2 spec Phase 1):
Slurm data is collected centrally rather than per-node.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx
from kafka import KafkaProducer

SLURMRESTD_URL = os.environ.get("SLURMRESTD_URL", "http://slurmrestd:6820")
SLURMRESTD_TOKEN = os.environ.get("SLURMRESTD_TOKEN", "")
KAFKA_BROKERS = os.environ.get("KAFKA_BROKERS", "redpanda:9092").split(",")
TOPIC = "slurm.jobs"
POLL_INTERVAL_S = 30


def fetch_jobs(client: httpx.Client) -> list[dict]:
    resp = client.get(
        f"{SLURMRESTD_URL}/slurm/v0.0.40/jobs",
        headers={"X-SLURM-USER-TOKEN": SLURMRESTD_TOKEN},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json().get("jobs", [])


def _split_top_level(expr: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in expr:
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += {"[": 1, "]": -1}.get(ch, 0)
        cur += ch
    return [p for p in parts + [cur] if p]


def expand_hostlist(expr: str) -> list[str]:
    """Expand a Slurm hostlist expression: 'gpu[001-003,007],cpu1' -> gpu001..gpu003, gpu007, cpu1."""
    hosts: list[str] = []
    for part in _split_top_level(expr):
        lb = part.find("[")
        if lb == -1:
            hosts.append(part)
            continue
        rb = part.index("]", lb)
        prefix, body, rest = part[:lb], part[lb + 1:rb], part[rb + 1:]
        suffixes = expand_hostlist(rest) if rest else [""]  # further groups: 'r[1-2]n[1-2]'
        for rng in body.split(","):
            lo, _, hi = rng.partition("-")
            width = len(lo)  # zero-padding is taken from the low bound, as Slurm does
            for n in range(int(lo), int(hi or lo) + 1):
                hosts.extend(prefix + str(n).zfill(width) + s for s in suffixes)
    return hosts


def _number(field: object) -> int | None:
    # v0.0.40 wraps numbers as {"set": bool, "infinite": bool, "number": int}
    if isinstance(field, dict):
        return field.get("number") if field.get("set", True) else None
    return field  # type: ignore[return-value]


def to_record(job: dict) -> dict | None:
    """None for jobs that haven't started: `jobs` is keyed on start_time, so publishing a
    pending job with start 0 would leave a row that never merges with its running copy."""
    start_time = _number(job.get("start_time"))
    if not start_time:
        return None
    end_time = _number(job.get("end_time"))
    return {
        "job_id": str(job.get("job_id")),
        "user": job.get("user_name"),
        "partition": job.get("partition"),
        "node_list": expand_hostlist(job.get("nodes") or ""),
        "state": (job.get("job_state") or ["UNKNOWN"])[0],
        "start_time": start_time,
        "end_time": end_time or None,
        "exit_code": _number((job.get("exit_code") or {}).get("return_code")),
        "priority": _number(job.get("priority")),
        "polled_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )
    with httpx.Client() as client:
        while True:
            try:
                jobs = fetch_jobs(client)
                records = [r for r in map(to_record, jobs) if r is not None]
                for r in records:
                    producer.send(TOPIC, r)
                producer.flush()
                print(f"[slurm-poller] published {len(records)} of {len(jobs)} job records")
            except Exception as exc:  # keep polling; transient slurmrestd/network errors expected
                print(f"[slurm-poller] poll failed: {exc}")
            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
