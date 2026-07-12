"""CLI entry point for the resumable full-market ML pipeline."""
from __future__ import annotations

import argparse
import hashlib
import os
import json
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.full_market_ml.config import load_full_market_ml_config
from app.evaluation.full_market_ml.pipeline import FullMarketMLPipeline, STAGES, select_probe_dates


RUN_ID = "fm_rank_10d_20260710_r1"


def default_services():
    """Bind the CLI to the established research-only module contracts."""
    import pandas as pd
    import pyarrow.parquet as pq
    import tushare as ts

    from app.evaluation.full_market_ml.collector import collect_full_market_raw
    from app.evaluation.full_market_ml.evaluator import evaluate_ranking
    from app.evaluation.full_market_ml.feature_audit import audit_features
    from app.evaluation.full_market_ml.features import build_cross_section_features, build_time_series_features
    from app.evaluation.full_market_ml.labels import aggregate_full_market_labels, build_forward_labels
    from app.evaluation.full_market_ml.manifests import load_manifest
    from app.evaluation.full_market_ml.panel import build_full_market_panel
    from app.evaluation.full_market_ml.preflight import run_preflight
    from app.evaluation.full_market_ml.quality import audit_panel_quality
    from app.evaluation.full_market_ml.splits import SplitPlan, WalkForwardFold, build_split_plan
    from app.evaluation.full_market_ml.trainer import FrozenCandidate, run_development_training, run_final_holdout_evaluation

    client = ts.pro_api(os.environ.get("TUSHARE_TOKEN", ""))

    def artifact(root, name):
        path = root / "artifacts" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_json(path, value):
        path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str, indent=2) + "\n", encoding="utf-8")

    def file_sha256(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def feature_schema_sha256(candidate):
        payload = json.dumps({"selected_features": list(candidate.selected_features)}, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def metric_rows(metrics_by_name):
        rows = []
        for name, metrics in metrics_by_name.items():
            rows.extend({"scope": name, "metric": metric, "value": value} for metric, value in metrics.items())
        return rows

    def write_model_card(path, candidate, evaluation, split):
        lines = [
            "# Full-Market ML Model Card",
            "",
            f"- Status: `{evaluation.model_status}`",
            f"- Frozen candidate SHA: `{candidate.frozen_model_sha256}`",
            f"- Split SHA: `{split.split_sha256}`",
            "- Selection source: `A_walk_forward_oof` only.",
            "- Final evaluation quadrants: B (time holdout), C (unseen stocks), D (joint holdout).",
            "- Production integration: prohibited by this research-only run.",
            "",
            "## Failed Gates",
            "",
        ]
        if evaluation.failed_gates:
            lines.extend(f"- `{gate}`" for gate in evaluation.failed_gates)
        else:
            lines.append("- None")
        lines.extend(["", "## Holdout Metrics", ""])
        for quadrant, metrics in evaluation.quadrant_metrics.items():
            lines.append(f"### {quadrant}")
            lines.append("")
            lines.append(f"- Precision@5: `{metrics.get('precision_at_5')}`")
            lines.append(f"- NDCG@10: `{metrics.get('ndcg_at_10')}`")
            lines.append(f"- Top5 mean return: `{metrics.get('top_5_mean_return')}`")
            lines.append(f"- Severe negative rate: `{metrics.get('severe_negative_rate')}`")
            lines.append("")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def panel_dataset(root):
        paths = sorted((root / "panel" / "stage=full-build").glob("shard=*/data.parquet"))
        return {path.parent.name: pq.read_table(path).to_pandas() for path in paths}

    def load_split(root):
        raw = json.loads((artifact(root, "full-build") / "split_plan.json").read_text(encoding="utf-8"))
        quadrants = raw["quadrants"]
        folds = tuple(WalkForwardFold(**{key: tuple(value) if key in {"training_dates", "validation_dates", "training_symbols"} else value for key, value in fold.items()}) for fold in raw["walk_forward"])
        return SplitPlan(
            development_dates=tuple(raw["development_dates"]), final_dates=tuple(raw["final_dates"]),
            stock_holdout_symbols=tuple(raw["stock_holdout_symbols"]),
            A_dev_train_symbols=tuple(quadrants["A_dev_train_symbols"]), B_final_train_symbols=tuple(quadrants["B_final_train_symbols"]),
            C_dev_unseen_symbols=tuple(quadrants["C_dev_unseen_symbols"]), D_final_unseen_symbols=tuple(quadrants["D_final_unseen_symbols"]),
            walk_forward=folds, stratum_counts_before=raw["stratum_counts_before"], stratum_counts_after=raw["stratum_counts_after"],
            split_sha256=raw["split_sha256"], final_holdout_frozen_model_sha=raw.get("final_holdout_frozen_model_sha"),
        )

    def preflight(config, root, _artifacts):
        report = run_preflight(config, os.environ, client, runtime_root=root)
        return {"quality_ready": report["ready"], "blocking_codes": report["blocking_codes"], "preflight": report}

    def recent_window_config(config, calendar_days, sessions):
        end = date.fromisoformat(config.dates.signal_end)
        rows = client.trade_cal(
            exchange="",
            start_date=(end - timedelta(days=calendar_days)).strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        ).to_dict("records")
        dates = select_probe_dates(
            [str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1"],
            sessions,
        )
        return replace(config, dates=replace(config.dates, signal_start=dates[0], signal_end=dates[-1]))

    def probe_config(config):
        return recent_window_config(config, calendar_days=45, sessions=5)

    def pilot_config(config):
        # 130 sessions leave at least 100 labelable days after the 20-day horizon.
        return recent_window_config(config, calendar_days=300, sessions=130)

    def collect(stage, with_panel=False, bounded_probe=False):
        def handler(config, root, _artifacts):
            collection_config = probe_config(config) if bounded_probe else config
            manifest = collect_full_market_raw(collection_config, client, root, stage, resume=True)
            result = {"manifest": manifest.to_dict(), "quality_ready": manifest.ready, "blocking_codes": manifest.blocking_codes}
            if with_panel and manifest.ready:
                panel = build_full_market_panel(config, root, stage)
                result["panel_rows"] = panel.row_count
            return result
        return handler

    def full_build(config, root, _artifacts):
        manifest = collect_full_market_raw(config, client, root, "full-build", resume=True)
        if not manifest.ready:
            return {"quality_ready": False, "blocking_codes": manifest.blocking_codes}
        panel_root = root / "panel" / "stage=full-build"
        if not panel_root.exists():
            build_full_market_panel(config, root, "full-build")
        panels = panel_dataset(root)
        dataset = pd.concat(panels.values(), ignore_index=True)
        quality = audit_panel_quality(config, dataset, manifest)
        report_path = artifact(root, "full-build") / "quality_report.json"
        report_path.write_text(quality.to_json() + "\n", encoding="utf-8")
        if not quality.ready:
            return {"quality_ready": False, "blocking_codes": list(quality.blocking_codes), "quality_report": str(report_path)}
        labeled = aggregate_full_market_labels(config, {key: build_forward_labels(config, value) for key, value in panels.items()})
        features = build_cross_section_features(config, {key: build_time_series_features(config, value) for key, value in labeled.items()})
        complete = pd.concat(features.values(), ignore_index=True)
        output = artifact(root, "full-build")
        complete.to_parquet(output / "dataset.parquet", index=False)
        split = build_split_plan(config, complete)
        (output / "split_plan.json").write_text(json.dumps(split.to_dict(), ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
        return {"quality_ready": True, "dataset": str(output / "dataset.parquet"), "split_sha256": split.split_sha256}

    def feature_audit(config, root, _artifacts):
        dataset = pd.read_parquet(artifact(root, "full-build") / "dataset.parquet")
        split = load_split(root)
        development = dataset.loc[dataset["trade_date"].isin(split.development_dates)].copy()
        report = audit_features(development, split)
        output = artifact(root, "feature-audit") / "report.json"
        output.write_text(json.dumps(report.to_csv_rows(), ensure_ascii=True, default=str) + "\n", encoding="utf-8")
        return {"quality_ready": True, "feature_audit": str(output)}

    def dev_train(config, root, _artifacts):
        dataset_path = artifact(root, "full-build") / "dataset.parquet"
        dataset = pd.read_parquet(dataset_path)
        split = load_split(root)
        development = dataset.loc[dataset["trade_date"].isin(split.development_dates)].copy()
        candidate = run_development_training(config, development, split)
        output = artifact(root, "dev-train") / "oof_predictions.parquet"
        candidate.oof_predictions.to_parquet(output, index=False)
        manifest = candidate.manifest(
            config_sha256=config.sha256,
            data_sha256=file_sha256(dataset_path),
            feature_schema_sha256=feature_schema_sha256(candidate),
        )
        manifest_path = artifact(root, "dev-train") / "candidate_manifest.json"
        write_json(manifest_path, manifest)
        return {
            "quality_ready": True,
            "frozen_model_sha": candidate.frozen_model_sha256,
            "frozen_model_manifest": manifest,
            "preliminary_status": candidate.preliminary_status,
            "oof_predictions": str(output),
            "candidate_manifest": str(manifest_path),
        }

    def final_evaluate(_config, root, _artifacts):
        # No deployment decision is made here; this is an immutable research report.
        predictions = pd.read_parquet(artifact(root, "dev-train") / "oof_predictions.parquet")
        report = {"status": "research_only", "scope": "frozen_development_oof", "ranking": evaluate_ranking(predictions)}
        output = artifact(root, "final-evaluate") / "evaluation.json"
        output.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
        return {"quality_ready": True, "evaluation": str(output), "status": report["status"]}

    def final_holdout_evaluate(config, root, _artifacts):
        dataset_path = artifact(root, "full-build") / "dataset.parquet"
        split = load_split(root)
        frozen_sha = str(json.loads((root / "frozen_model_manifest.json").read_text(encoding="utf-8"))["frozen_model_sha"])
        dates = pd.read_parquet(dataset_path, columns=["trade_date", "eligible_for_training"])
        dates["trade_date"] = pd.to_datetime(dates["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        labelable_final_dates = dates.loc[
            dates["trade_date"].isin(split.final_dates) & dates["eligible_for_training"].eq(True), "trade_date"
        ].nunique()
        if labelable_final_dates < 40:
            raise ValueError(
                f"final holdout has only {labelable_final_dates} labelable trade dates; requires at least 40 before opening the sealed holdout"
            )
        dataset = pd.read_parquet(dataset_path)
        candidate_manifest = json.loads((artifact(root, "dev-train") / "candidate_manifest.json").read_text(encoding="utf-8"))
        candidate = FrozenCandidate.from_manifest(candidate_manifest)
        if candidate.frozen_model_sha256 != frozen_sha:
            raise ValueError("frozen candidate manifest SHA does not match the sealed manifest")
        evaluation = run_final_holdout_evaluation(
            config,
            dataset,
            split,
            candidate,
            frozen_model_sha=frozen_sha,
        )
        output = artifact(root, "final-holdout-evaluate")
        predictions_path = output / "predictions.parquet"
        evaluation.predictions.to_parquet(predictions_path, index=False)
        pd.DataFrame(metric_rows(evaluation.quadrant_metrics)).to_csv(root / "holdout_metrics.csv", index=False)
        baseline_rows = []
        for quadrant, baselines in evaluation.baseline_metrics.items():
            for baseline, values in baselines.items():
                baseline_rows.extend(
                    {"quadrant": quadrant, "baseline": baseline, "metric": key, "value": value}
                    for key, value in values.items()
                )
        pd.DataFrame(baseline_rows).to_csv(root / "baseline_comparison.csv", index=False)
        calibration_rows = []
        for quadrant, report in evaluation.calibration.items():
            calibration_rows.append({"quadrant": quadrant, "bin": 0, "count": None, "mean_predicted_probability": None, "hit_rate": None, "brier": report["brier"], "ece": report["ece"]})
            calibration_rows.extend({"quadrant": quadrant, **row, "brier": None, "ece": None} for row in report["bins"])
        pd.DataFrame(calibration_rows).to_csv(root / "calibration.csv", index=False)
        pd.DataFrame(metric_rows(evaluation.bootstrap)).to_csv(root / "bootstrap_metrics.csv", index=False)
        error_rows = []
        for quadrant, rows in evaluation.predictions.groupby("quadrant", sort=True):
            ranked = rows.sort_values(["score", "symbol"], ascending=[False, True], kind="stable").groupby("trade_date", sort=True).head(5)
            error_rows.append(ranked.loc[ranked["label_severe_negative_10d"].astype(bool)])
        pd.concat(error_rows, ignore_index=True).to_csv(root / "error_cases.csv", index=False)
        metrics = {
            "model_status": evaluation.model_status,
            "gate_results": {"failed": evaluation.failed_gates},
            "time_holdout": evaluation.quadrant_metrics["B_time_holdout"],
            "stock_holdout": evaluation.quadrant_metrics["C_stock_holdout"],
            "joint_holdout": evaluation.quadrant_metrics["D_joint_holdout"],
            "portfolios": evaluation.portfolios,
            "labelable_final_dates": labelable_final_dates,
        }
        write_json(root / "model_metrics.json", metrics)
        write_model_card(root / "model_card.md", candidate, evaluation, split)
        manifest = candidate.manifest(
            config_sha256=config.sha256,
            data_sha256=file_sha256(dataset_path),
            feature_schema_sha256=feature_schema_sha256(candidate),
        )
        write_json(output / "candidate_manifest.json", manifest)
        return {
            "quality_ready": True,
            "model_status": evaluation.model_status,
            "holdout_metrics": str(root / "holdout_metrics.csv"),
            "model_metrics": str(root / "model_metrics.json"),
            "model_card": str(root / "model_card.md"),
            "predictions": str(predictions_path),
        }

    return {"preflight": preflight, "probe": collect("probe", bounded_probe=True), "pilot-build": lambda config, root, artifacts: collect("pilot-build", with_panel=True)(pilot_config(config), root, artifacts), "full-build": full_build, "feature-audit": feature_audit, "dev-train": dev_train, "final-evaluate": final_evaluate, "final-holdout-evaluate": final_holdout_evaluate}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--frozen-model-sha")
    parser.add_argument("--run-id", default=RUN_ID)
    arguments = parser.parse_args()
    config = load_full_market_ml_config(arguments.config)
    root = Path(__file__).resolve().parents[2] / "runtime" / "ml_full_market" / "runs" / arguments.run_id
    result = FullMarketMLPipeline(config, root, default_services()).run(
        arguments.stage, resume=arguments.resume, frozen_model_sha=arguments.frozen_model_sha
    )
    print(json.dumps({"stage": result.stage, "reused_stages": result.reused_stages}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
