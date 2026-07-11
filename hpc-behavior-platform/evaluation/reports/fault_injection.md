# Fault Injection Report

Phase 4/7 gate: recall >= 0.9 at |z| >= 3. See evaluation/tests/test_fault_injection.py for why two fault types are documented gaps rather than forced passes.

| fault | band | recall@|z|>=3 | gate |
|---|---|---|---|
| cpu_steal | 2h | 1.00 | PASS |
| memory_leak_ramp | 7d | 0.00 | documented gap |
| ib_error_burst | 2h | 0.00 | documented gap |
| dead_node | 2h | 1.00 | PASS |
