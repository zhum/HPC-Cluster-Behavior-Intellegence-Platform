# Fault Injection Report

Phase 4/7 gate: recall >= 0.9 at |z| >= 3. Per-fault detection settings (band, max_cycles, min_finest_window) are empirically characterized in evaluation/fault_injection.py FAULT_DETECTION.

| fault | band | max_cycles | min_finest_window | recall@|z|>=3 | gate |
|---|---|---|---|---|---|
| cpu_steal | 2h | 1 | 32 | 1.00 | PASS |
| memory_leak_ramp | 2h | 1 | 32 | 1.00 | PASS |
| ib_error_burst | 5m | 8 | 16 | 1.00 | PASS |
| dead_node | 2h | 1 | 32 | 1.00 | PASS |
