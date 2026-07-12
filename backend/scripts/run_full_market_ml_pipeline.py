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
from app.evaluation.full_market_ml.assets import (
    backup_dataset_assets,
    backup_stage_assets,
    build_dataset_registry,
    verify_dataset_backup,
    write_dataset_registry,
)


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
    from app.evaluation.full_market_ml.trainer import (
        FrozenCandidate,
        fit_final_candidate,
        load_final_fit,
        run_development_training,
        run_final_holdout_evaluation,
        save_final_fit,
    )

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

    def frozen_candidate(root):
        frozen_sha = str(json.loads((root / "frozen_model_manifest.json").read_text(encoding="utf-8"))["frozen_model_sha"])
        candidate_manifest = json.loads((artifact(root, "dev-train") / "candidate_manifest.json").read_text(encoding="utf-8"))
        candidate = FrozenCandidate.from_manifest(candidate_manifest)
        if candidate.frozen_model_sha256 != frozen_sha:
            raise ValueError("frozen candidate manifest SHA does not match the sealed manifest")
        return frozen_sha, candidate

    def write_development_gate_skip(root, stage, candidate, frozen_sha):
        output = artifact(root, stage) / "skipped.json"
        write_json(output, {
            "status": "research_only_failed_gate",
            "reason": "development_gate_failed",
            "failed_gates": candidate.failed_gates,
            "frozen_model_sha": frozen_sha,
        })
        return {"quality_ready": True, "status": "research_only_failed_gate", "skipped": str(output)}

    def verified_backup(root):
        backup_root = os.environ.get("ML_BACKUP_ROOT", "").strip()
        if not backup_root:
            raise ValueError("ML_BACKUP_ROOT is required before formal final-fit")
        registry_path = artifact(root, "full-build") / "dataset_registry.json"
        if not registry_path.is_file():
            raise FileNotFoundError("dataset registry is required before formal final-fit")
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        verify_dataset_backup(backup_root, registry)
        return Path(backup_root), registry

    def final_fit(_config, root, _artifacts):
        frozen_sha, candidate = frozen_candidate(root)
        if not candidate.can_open_final_holdout:
            return write_development_gate_skip(root, "final-fit", candidate, frozen_sha)
        backup_root, registry = verified_backup(root)
        split = load_split(root)
        dataset_path = artifact(root, "full-build") / "dataset.parquet"
        development = pd.read_parquet(dataset_path, filters=[("trade_date", "in", list(split.development_dates))])
        fitted = fit_final_candidate(development, split, candidate, frozen_model_sha=frozen_sha)
        output = artifact(root, "final-fit") / "model"
        save_final_fit(fitted, output)
        backup_stage_assets(root, backup_root, registry, stage="final-fit", artifact_id=frozen_sha)
        backup_manifest = backup_root / registry["dataset_id"] / "derived" / "final-fit" / frozen_sha / "backup_manifest.json"
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = {
            "quality_ready": True,
            "status": "complete",
            "final_fit_manifest": str(manifest_path),
            "backup_manifest": str(backup_manifest),
        }
        for group in ("rank_models", "strong_models", "severe_models"):
            for index, model in enumerate(manifest[group]):
                result[f"{group}_{index:02d}"] = str(output / model["file"])
        return result

    def final_holdout_evaluate(config, root, _artifacts):
        dataset_path = artifact(root, "full-build") / "dataset.parquet"
        split = load_split(root)
        frozen_sha, candidate = frozen_candidate(root)
        if not candidate.can_open_final_holdout:
            return write_development_gate_skip(root, "final-holdout-evaluate", candidate, frozen_sha)
        backup_root, registry = verified_backup(root)
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
        output = artifact(root, "final-holdout-evaluate")
        final_fit = load_final_fit(artifact(root, "final-fit") / "model", frozen_sha)
        quadrant_paths = {}

        def persist_quadrant(quadrant, rows):
            path = output / "predictions" / f"{quadrant}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            rows.to_parquet(path, index=False)
            quadrant_paths[quadrant] = path

        evaluation = run_final_holdout_evaluation(
            config,
            dataset,
            split,
            candidate,
            frozen_model_sha=frozen_sha,
            final_fit=final_fit,
            on_quadrant_complete=persist_quadrant,
        )
        predictions_path = output / "predictions.parquet"
        evaluation.predictions.to_parquet(predictions_path, index=False)
        pd.DataFrame(metric_rows(evaluation.quadrant_metrics)).to_csv(output / "holdout_metrics.csv", index=False)
        baseline_rows = []
        for quadrant, baselines in evaluation.baseline_metrics.items():
            for baseline, values in baselines.items():
                baseline_rows.extend(
                    {"quadrant": quadrant, "baseline": baseline, "metric": key, "value": value}
                    for key, value in values.items()
                )
        pd.DataFrame(baseline_rows).to_csv(output / "baseline_comparison.csv", index=False)
        calibration_rows = []
        for quadrant, report in evaluation.calibration.items():
            calibration_rows.append({"quadrant": quadrant, "bin": 0, "count": None, "mean_predicted_probability": None, "hit_rate": None, "brier": report["brier"], "ece": report["ece"]})
            calibration_rows.extend({"quadrant": quadrant, **row, "brier": None, "ece": None} for row in report["bins"])
        pd.DataFrame(calibration_rows).to_csv(output / "calibration.csv", index=False)
        pd.DataFrame(metric_rows(evaluation.bootstrap)).to_csv(output / "bootstrap_metrics.csv", index=False)
        error_rows = []
        for quadrant, rows in evaluation.predictions.groupby("quadrant", sort=True):
            ranked = rows.sort_values(["score", "symbol"], ascending=[False, True], kind="stable").groupby("trade_date", sort=True).head(5)
            error_rows.append(ranked.loc[ranked["label_severe_negative_10d"].astype(bool)])
        pd.concat(error_rows, ignore_index=True).to_csv(output / "error_cases.csv", index=False)
        metrics = {
            "model_status": evaluation.model_status,
            "gate_results": {"failed": evaluation.failed_gates},
            "time_holdout": evaluation.quadrant_metrics["B_time_holdout"],
            "stock_holdout": evaluation.quadrant_metrics["C_stock_holdout"],
            "joint_holdout": evaluation.quadrant_metrics["D_joint_holdout"],
            "portfolios": evaluation.portfolios,
            "labelable_final_dates": labelable_final_dates,
        }
        write_json(output / "model_metrics.json", metrics)
        write_model_card(output / "model_card.md", candidate, evaluation, split)
        manifest = candidate.manifest(
            config_sha256=config.sha256,
            data_sha256=file_sha256(dataset_path),
            feature_schema_sha256=feature_schema_sha256(candidate),
        )
        write_json(output / "candidate_manifest.json", manifest)
        backup_stage_assets(root, backup_root, registry, stage="final-holdout-evaluate", artifact_id=frozen_sha)
        backup_manifest = backup_root / registry["dataset_id"] / "derived" / "final-holdout-evaluate" / frozen_sha / "backup_manifest.json"
        return {
            "quality_ready": True,
            "model_status": evaluation.model_status,
            "holdout_metrics": str(output / "holdout_metrics.csv"),
            "model_metrics": str(output / "model_metrics.json"),
            "model_card": str(output / "model_card.md"),
            "predictions": str(predictions_path),
            "backup_manifest": str(backup_manifest),
            **{f"prediction_{quadrant}": str(path) for quadrant, path in sorted(quadrant_paths.items())},
        }

    return {"preflight": preflight, "probe": collect("probe", bounded_probe=True), "pilot-build": lambda config, root, artifacts: collect("pilot-build", with_panel=True)(pilot_config(config), root, artifacts), "full-build": full_build, "feature-audit": feature_audit, "dev-train": dev_train, "final-evaluate": final_evaluate, "final-fit": final_fit, "final-holdout-evaluate": final_holdout_evaluate}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--frozen-model-sha")
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--abort-stage", choices=STAGES)
    parser.add_argument("--abort-reason", default="operator_requested_abort")
    parser.add_argument("--register-assets", action="store_true")
    parser.add_argument("--backup-root")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--recover-stale-seconds", type=int)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "runtime" / "ml_full_market" / "runs" / arguments.run_id
    if arguments.status:
        print(json.dumps(FullMarketMLPipeline.inspect_runtime(root), ensure_ascii=True, sort_keys=True))
        return 0
    if not arguments.config:
        parser.error("--config is required unless --status is supplied")
    config = load_full_market_ml_config(arguments.config)
    pipeline = FullMarketMLPipeline(config, root, default_services())
    if arguments.recover_stale_seconds is not None:
        recovered = pipeline.recover_stale_stages(max_idle_seconds=arguments.recover_stale_seconds)
        print(json.dumps({"recovered_stages": recovered}, ensure_ascii=True, sort_keys=True))
        return 0
    if arguments.abort_stage:
        state = pipeline.abort_stage(arguments.abort_stage, reason=arguments.abort_reason)
        print(json.dumps({"stage": arguments.abort_stage, "status": state["status"]}, ensure_ascii=True, sort_keys=True))
        return 0
    if arguments.register_assets:
        registry = build_dataset_registry(root, code_revision=os.environ.get("GIT_COMMIT", "unknown"))
        registry_path = write_dataset_registry(root, registry)
        if arguments.backup_root:
            result = backup_dataset_assets(root, arguments.backup_root, registry)
            print(json.dumps({"dataset_id": registry["dataset_id"], "backup": result}, ensure_ascii=True, sort_keys=True))
        else:
            print(json.dumps({"dataset_id": registry["dataset_id"], "registry": str(registry_path)}, ensure_ascii=True, sort_keys=True))
        return 0
    if not arguments.stage:
        parser.error("--stage is required unless --abort-stage, --register-assets, --status, or --recover-stale-seconds is supplied")
    result = pipeline.run(
        arguments.stage, resume=arguments.resume, frozen_model_sha=arguments.frozen_model_sha
    )
    print(json.dumps({"stage": result.stage, "reused_stages": result.reused_stages}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
