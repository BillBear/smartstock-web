#!/usr/bin/env python3
"""Compare offline recall experiment ranking evidence without changing production strategy."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.recall_experiments import build_recall_experiment_report, write_recall_experiment_report


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline SmartStock recall experiment comparison report.")
    parser.add_argument("--experiment-root", required=True, help="Directory containing per-experiment ranking_summary.json files.")
    parser.add_argument("--output-json", required=True, help="Path to write recall_experiment_report.json.")
    parser.add_argument("--output-md", required=True, help="Path to write a Markdown summary.")
    return parser.parse_args(argv)


def run(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    report = build_recall_experiment_report(Path(args.experiment_root))
    json_path = write_recall_experiment_report(report, Path(args.output_json))
    md_path = write_markdown_report(report, Path(args.output_md))
    print(f"wrote json: {json_path}")
    print(f"wrote markdown: {md_path}")
    print(f"status: {report.get('status')}")
    print(f"production_switch_ready: {report.get('production_switch_ready')}")
    return 0


def write_markdown_report(report: dict, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Recall Experiment Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- production_switch_ready: `{str(report.get('production_switch_ready')).lower()}`",
        f"- blocking_reasons: `{', '.join(report.get('blocking_reasons') or []) or '-'}`",
        "",
        "| experiment | evidence | Precision@3 | Precision@5 | NDCG@10 | Top5 Avg Return | Max Drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("experiments") or []:
        metrics = row.get("metrics") or {}
        lines.append(
            "| {key} | {evidence} | {p3:.4f} | {p5:.4f} | {ndcg:.4f} | {ret:.4f} | {dd:.4f} |".format(
                key=row.get("key"),
                evidence=row.get("evidence_status"),
                p3=float(metrics.get("precision_at_3") or 0.0),
                p5=float(metrics.get("precision_at_5") or 0.0),
                ndcg=float(metrics.get("ndcg_at_10") or 0.0),
                ret=float(metrics.get("top_5_avg_return_pct") or 0.0),
                dd=float(metrics.get("max_drawdown") or 0.0),
            )
        )
    lines.extend(
        [
            "",
            "This is an offline comparison artifact. It does not change production selection, ranking, buy/sell, stop, or position logic.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    raise SystemExit(run())
