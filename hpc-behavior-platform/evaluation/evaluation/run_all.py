"""Regenerates the markdown report artifacts under evaluation/reports/.

    python -m evaluation.run_all
"""
from __future__ import annotations

from pathlib import Path

from evaluation.dr_ablation import run_ablation
from evaluation.dr_ablation import write_markdown_report as write_ablation_report
from evaluation.fault_injection import FAULT_DETECTION, FAULTS, run_fault_case
from evaluation.fixtures import planted_cluster_tensor
from evaluation.quality_benchmark import benchmark_report, write_markdown_report as write_quality_report

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"



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
        "Phase 4/7 gate: recall >= 0.9 at |z| >= 3. Per-fault detection "
        "settings (band, max_cycles, min_finest_window) are empirically "
        "characterized in evaluation/fault_injection.py FAULT_DETECTION.",
        "",
        "| fault | band | max_cycles | min_finest_window | recall@|z|>=3 | gate |",
        "|---|---|---|---|---|---|",
    ]
    for fault in FAULTS:
        cfg = FAULT_DETECTION[fault]
        result = run_fault_case(
            fault, band=cfg.band, max_cycles=cfg.max_cycles, min_finest_window=cfg.min_finest_window
        )
        gate = "PASS" if result["recall_at_3"] >= 0.9 else "FAIL"
        lines.append(
            f"| {fault} | {cfg.band} | {cfg.max_cycles} | {cfg.min_finest_window} "
            f"| {result['recall_at_3']:.2f} | {gate} |"
        )
    (REPORTS_DIR / "fault_injection.md").write_text("\n".join(lines) + "\n")

    print(f"reports written to {REPORTS_DIR}")


if __name__ == "__main__":
    main()
