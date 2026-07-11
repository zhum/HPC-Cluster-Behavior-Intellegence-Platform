"""Regenerates the markdown report artifacts under evaluation/reports/.

    python -m evaluation.run_all
"""
from __future__ import annotations

from pathlib import Path

from evaluation.dr_ablation import run_ablation
from evaluation.dr_ablation import write_markdown_report as write_ablation_report
from evaluation.fault_injection import FAULTS, run_fault_case
from evaluation.fixtures import planted_cluster_tensor
from evaluation.quality_benchmark import benchmark_report, write_markdown_report as write_quality_report

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

# (fault, band) pairs as empirically characterized in tests/test_fault_injection.py
FAULT_BANDS = {
    "cpu_steal": "2h",
    "memory_leak_ramp": "7d",
    "ib_error_burst": "2h",
    "dead_node": "2h",
}


def main() -> None:
    REPORTS_DIR.mkdir(exist_ok=True)

    X, true_labels = planted_cluster_tensor()

    quality_results = [benchmark_report(X, true_labels, k=4, dataset_name="synthetic_planted")]
    write_quality_report(quality_results, REPORTS_DIR / "quality_benchmark.md")

    ablation_report = run_ablation(X, true_labels, k=4)
    write_ablation_report(ablation_report, REPORTS_DIR / "dr_ablation.md")

    try:
        from evaluation.research_contrastive import run_contrastive_vs_multidr
        from evaluation.research_contrastive import write_markdown_report as write_research_report

        research_result = run_contrastive_vs_multidr(X, true_labels, k=4)
        write_research_report(research_result, REPORTS_DIR / "research_contrastive.md")
    except ImportError:
        print("skipping research_contrastive report: install the 'research' extra (torch) to generate it")

    lines = [
        "# Fault Injection Report",
        "",
        "Phase 4/7 gate: recall >= 0.9 at |z| >= 3. See "
        "evaluation/tests/test_fault_injection.py for why two fault types are "
        "documented gaps rather than forced passes.",
        "",
        "| fault | band | recall@|z|>=3 | gate |",
        "|---|---|---|---|",
    ]
    for fault in FAULTS:
        band = FAULT_BANDS[fault]
        result = run_fault_case(fault, band=band)
        gate = "PASS" if result["recall_at_3"] >= 0.9 else "documented gap"
        lines.append(f"| {fault} | {band} | {result['recall_at_3']:.2f} | {gate} |")
    (REPORTS_DIR / "fault_injection.md").write_text("\n".join(lines) + "\n")

    print(f"reports written to {REPORTS_DIR}")


if __name__ == "__main__":
    main()
