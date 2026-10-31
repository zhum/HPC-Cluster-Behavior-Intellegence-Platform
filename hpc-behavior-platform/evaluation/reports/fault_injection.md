# Fault Injection Report

Phase 4/7 gate: on every seed 0-9, recall >= 0.9 at |z| >= 3 and at most 10% of healthy nodes flagged. Columns show the worst seed. Per-fault detection settings (band, max_cycles, min_finest_window) are in evaluation/fault_injection.py FAULT_DETECTION.

| fault | band | max_cycles | min_finest_window | min recall | max false-positive rate | gate |
|---|---|---|---|---|---|---|
| cpu_steal | 5m | 16 | 32 | 1.00 | 0.00 | PASS |
| memory_leak_ramp | 2h | 1 | 32 | 1.00 | 0.00 | PASS |
| ib_error_burst | 5m | 8 | 16 | 0.25 | 0.12 | FAIL |
| dead_node | 2h | 1 | 32 | 1.00 | 0.00 | PASS |
