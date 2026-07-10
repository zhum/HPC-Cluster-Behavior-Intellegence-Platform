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


def to_record(job: dict) -> dict:
    return {
        "job_id": str(job.get("job_id")),
        "user": job.get("user_name"),
        "partition": job.get("partition"),
        "node_list": job.get("nodes", "").split(",") if job.get("nodes") else [],
        "state": (job.get("job_state") or ["UNKNOWN"])[0],
        "start_time": job.get("start_time", {}).get("number"),
        "end_time": job.get("end_time", {}).get("number"),
        "exit_code": job.get("exit_code", {}).get("return_code"),
        "priority": job.get("priority", {}).get("number"),
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
                for job in jobs:
                    producer.send(TOPIC, to_record(job))
                producer.flush()
                print(f"[slurm-poller] published {len(jobs)} job records")
            except Exception as exc:  # keep polling; transient slurmrestd/network errors expected
                print(f"[slurm-poller] poll failed: {exc}")
            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
