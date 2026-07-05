from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def _bootstrap_paths() -> Path:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run read-only ML label/sample and feature diagnostics.")
    parser.add_argument("--sample-path", required=True)
    parser.add_argument("--run-dir", default=None, help="Optional existing ML run directory used to infer feature names.")
    parser.add_argument("--features", default="", help="Comma-separated feature names. Overrides run-dir dataset_meta.json.")
    parser.add_argument("--label-col", default="label_top20_10d")
    parser.add_argument("--return-col", default="future_return_10d_pct")
    parser.add_argument("--horizon-days", type=int, default=10)
    parser.add_argument("--min-daily-count", type=int, default=500)
    parser.add_argument("--min-full-market-daily-count", type=int, default=5000)
    parser.add_argument("--expected-label-rate", type=float, default=0.20)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_paths()
    from app.evaluation.ml_feature_diagnostics import diagnose_feature_effectiveness
    from app.evaluation.ml_label_sample_audit import audit_label_sample_quality

    args = parse_args(argv)
    sample_path = Path(args.sample_path)
    frame = _read_samples(sample_path)
    feature_names = _feature_names(args, frame)
    label_audit = audit_label_sample_quality(
        frame,
        label_col=args.label_col,
        return_col=args.return_col,
        horizon_days=int(args.horizon_days),
        min_daily_count=int(args.min_daily_count),
        min_full_market_daily_count=int(args.min_full_market_daily_count),
        expected_label_rate=float(args.expected_label_rate),
    )
    feature_diagnostics = diagnose_feature_effectiveness(
        frame,
        feature_names=feature_names,
        label_col=args.label_col,
        return_col=args.return_col,
    )
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sample_path": str(sample_path),
        "run_dir": args.run_dir,
        "label_col": args.label_col,
        "return_col": args.return_col,
        "feature_names": feature_names,
        "label_sample_audit": label_audit,
        "feature_diagnostics": feature_diagnostics,
        "model_promotion_allowed": bool(
            label_audit.get("safe_for_model_promotion")
            and not feature_diagnostics.get("warnings")
            and feature_diagnostics.get("tree", {}).get("status") == "trained"
        ),
    }
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(_to_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(output_json),
                "output_md": str(output_md),
                "model_promotion_allowed": report["model_promotion_allowed"],
                "finding_count": len(label_audit.get("findings") or []),
                "feature_warning_count": len(feature_diagnostics.get("warnings") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_samples(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    raise ValueError(f"Unsupported sample file type: {path}")


def _feature_names(args, frame: pd.DataFrame) -> List[str]:
    if args.features:
        return [item.strip() for item in str(args.features).split(",") if item.strip()]
    if args.run_dir:
        meta_path = Path(args.run_dir) / "dataset_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            features = meta.get("feature_names") or []
            if features:
                return [str(item) for item in features]
    blocked_prefixes = ("label_", "future_")
    excluded = {"date", "trade_date", "symbol", "name", "split"}
    inferred = []
    for column in frame.columns:
        if column in excluded or str(column).startswith(blocked_prefixes):
            continue
        if pd.api.types.is_numeric_dtype(frame[column]):
            inferred.append(str(column))
    return inferred


def _to_markdown(report: Dict[str, Any]) -> str:
    label_audit = report["label_sample_audit"]
    feature_diag = report["feature_diagnostics"]
    summary = label_audit.get("summary") or {}
    lines = [
        "# ML Label and Feature Diagnostics",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Conclusion",
        "",
    ]
    if report["model_promotion_allowed"]:
        lines.append("The sample and feature diagnostics did not find blocking issues.")
    else:
        lines.append("The current sample/model evidence is **not** sufficient for model promotion.")
    lines.extend(
        [
            "",
            "## Dataset Grain",
            "",
            f"- rows: `{summary.get('row_count', 0)}`",
            f"- symbols: `{summary.get('symbol_count', 0)}`",
            f"- dates: `{summary.get('date_count', 0)}`",
            f"- min / median / max daily rows: `{summary.get('min_daily_count', 0)}` / `{summary.get('median_daily_count', 0)}` / `{summary.get('max_daily_count', 0)}`",
            f"- label rate: `{summary.get('label_rate', 0)}`",
            f"- return mean: `{summary.get('return_mean', 0)}`",
            "",
            "## Label And Sample Findings",
            "",
        ]
    )
    findings = label_audit.get("findings") or []
    if findings:
        for finding in findings:
            lines.append(f"- `{finding.get('severity')}` `{finding.get('code')}`: {finding.get('message')}")
    else:
        lines.append("- No label/sample findings.")

    lines.extend(["", "## Decision Tree Diagnostics", ""])
    tree = feature_diag.get("tree") or {}
    lines.append(f"- status: `{tree.get('status')}`")
    for split_name in ("final_holdout", "stock_holdout"):
        metrics = tree.get(split_name) or {}
        lines.append(
            "- {split}: Precision@5 `{p5}`, NDCG@10 `{ndcg}`, Top5 return `{ret}`".format(
                split=split_name,
                p5=metrics.get("precision_at_5", 0),
                ndcg=metrics.get("ndcg_at_10", 0),
                ret=metrics.get("top5_return", 0),
            )
        )
    if tree.get("rules"):
        lines.extend(["", "```text", str(tree.get("rules")).strip(), "```"])

    lines.extend(["", "## Strongest Daily Univariate Features", ""])
    rows = []
    for feature, metrics in (feature_diag.get("daily_univariate") or {}).items():
        rows.append((feature, metrics))
    rows.sort(key=lambda item: (item[1].get("precision_at_5") or 0, item[1].get("top5_return") or 0), reverse=True)
    lines.append("| Feature | Direction | Precision@5 | NDCG@10 | Top5 Return |")
    lines.append("|---|---|---:|---:|---:|")
    for feature, metrics in rows[:12]:
        lines.append(
            "| {feature} | {direction} | {p5} | {ndcg} | {ret} |".format(
                feature=feature,
                direction=metrics.get("best_direction"),
                p5=metrics.get("precision_at_5"),
                ndcg=metrics.get("ndcg_at_10"),
                ret=metrics.get("top5_return"),
            )
        )

    lines.extend(["", "## Permutation Importance", ""])
    for split_name in ("final_holdout", "stock_holdout"):
        lines.append(f"### {split_name}")
        items = (feature_diag.get("permutation_importance") or {}).get(split_name) or []
        if not items:
            lines.append("- No permutation importance available.")
            continue
        for item in items[:10]:
            lines.append(f"- `{item['feature']}`: mean `{item['importance_mean']}`, std `{item['importance_std']}`")

    lines.extend(["", "## Redundant Feature Pairs", ""])
    pairs = feature_diag.get("correlation_pairs") or []
    if pairs:
        for pair in pairs[:20]:
            lines.append(f"- `{pair['left']}` vs `{pair['right']}`: abs Spearman `{pair['abs_spearman']}`")
    else:
        lines.append("- No high-correlation feature pairs above threshold.")

    if feature_diag.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        for warning in feature_diag.get("warnings") or []:
            lines.append(f"- `{warning}`")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
