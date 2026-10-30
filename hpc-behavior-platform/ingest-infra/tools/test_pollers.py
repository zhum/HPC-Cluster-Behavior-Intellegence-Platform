"""Unit tests for the pure parts of ib_poller / slurm_poller. Run: pytest test_pollers.py"""
from ib_poller import to_rates
from slurm_poller import expand_hostlist, to_record


def test_expand_hostlist():
    assert expand_hostlist("") == []
    assert expand_hostlist("cpu017") == ["cpu017"]
    assert expand_hostlist("gpu[001-003,007],cpu1") == [
        "gpu001", "gpu002", "gpu003", "gpu007", "cpu1"
    ]
    assert expand_hostlist("n[8-10]") == ["n8", "n9", "n10"]
    assert expand_hostlist("r[1-2]n[1-2]-ib") == ["r1n1-ib", "r1n2-ib", "r2n1-ib", "r2n2-ib"]


def test_to_record_unwraps_v0040_numbers_and_expands_nodes():
    job = {
        "job_id": 42,
        "user_name": "alice",
        "partition": "gpu",
        "nodes": "gpu[01-02]",
        "job_state": ["COMPLETED"],
        "start_time": {"set": True, "infinite": False, "number": 1700000000},
        "end_time": {"set": True, "infinite": False, "number": 1700003600},
        "exit_code": {"status": ["SUCCESS"], "return_code": {"set": True, "number": 0}},
        "priority": {"set": True, "number": 100},
    }
    r = to_record(job)
    assert r["job_id"] == "42"
    assert r["node_list"] == ["gpu01", "gpu02"]
    assert (r["start_time"], r["end_time"], r["exit_code"], r["priority"]) == (
        1700000000, 1700003600, 0, 100
    )


def test_to_record_running_and_pending():
    running = {"job_id": 1, "nodes": "n1", "start_time": {"set": True, "number": 1700000000},
               "end_time": {"set": True, "number": 0}}
    assert to_record(running)["end_time"] is None
    pending = {"job_id": 2, "nodes": "", "start_time": {"set": True, "number": 0}}
    assert to_record(pending) is None


def test_to_rates_sums_ports_and_skips_resets():
    prev = {("mlx5_0", "1", "symbol_errors"): 10, ("mlx5_1", "1", "symbol_errors"): 100,
            ("mlx5_0", "1", "link_downed"): 5}
    curr = {("mlx5_0", "1", "symbol_errors"): 40, ("mlx5_1", "1", "symbol_errors"): 130,
            ("mlx5_0", "1", "link_downed"): 0,       # reset: excluded
            ("mlx5_2", "1", "symbol_errors"): 999}   # new port: no baseline yet
    assert to_rates(prev, curr, 15.0) == {"ib.symbol_errors": 4.0}
