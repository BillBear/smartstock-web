"""CLI entry point for the resumable full-market ML pipeline."""
from __future__ import annotations

import argparse
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
    from app.evaluation.full_market_ml.trainer import run_development_training

    client = ts.pro_api(os.environ.get("TUSHARE_TOKEN", ""))

    def artifact(root, name):
        path = root / "artifacts" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

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

    def probe_config(config):
        end = date.fromisoformat(config.dates.signal_end)
        rows = client.trade_cal(
            exchange="",
            start_date=(end - timedelta(days=45)).strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        ).to_dict("records")
        dates = select_probe_dates(
            [str(row["cal_date"]) for row in rows if str(row.get("is_open")) == "1"],
        )
        return replace(config, dates=replace(config.dates, signal_start=dates[0], signal_end=dates[-1]))

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
        report = audit_features(dataset.loc[dataset["trade_date"].lt(config.dates.holdout_start)].copy(), load_split(root))
        output = artifact(root, "feature-audit") / "report.json"
        output.write_text(json.dumps(report.to_csv_rows(), ensure_ascii=True, default=str) + "\n", encoding="utf-8")
        return {"quality_ready": True, "feature_audit": str(output)}

    def dev_train(config, root, _artifacts):
        dataset = pd.read_parquet(artifact(root, "full-build") / "dataset.parquet")
        candidate = run_development_training(config, dataset.loc[dataset["trade_date"].lt(config.dates.holdout_start)].copy(), load_split(root))
        output = artifact(root, "dev-train") / "oof_predictions.parquet"
        candidate.oof_predictions.to_parquet(output, index=False)
        return {"quality_ready": True, "frozen_model_sha": candidate.frozen_model_sha256, "preliminary_status": candidate.preliminary_status, "oof_predictions": str(output)}

    def final_evaluate(_config, root, _artifacts):
        # No deployment decision is made here; this is an immutable research report.
        predictions = pd.read_parquet(artifact(root, "dev-train") / "oof_predictions.parquet")
        report = {"status": "research_only", "scope": "frozen_development_oof", "ranking": evaluate_ranking(predictions)}
        output = artifact(root, "final-evaluate") / "evaluation.json"
        output.write_text(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
        return {"quality_ready": True, "evaluation": str(output), "status": report["status"]}

    return {"preflight": preflight, "probe": collect("probe", bounded_probe=True), "pilot-build": collect("pilot-build", with_panel=True), "full-build": full_build, "feature-audit": feature_audit, "dev-train": dev_train, "final-evaluate": final_evaluate}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--frozen-model-sha")
    arguments = parser.parse_args()
    config = load_full_market_ml_config(arguments.config)
    root = Path(__file__).resolve().parents[2] / "runtime" / "ml_full_market" / "runs" / RUN_ID
    result = FullMarketMLPipeline(config, root, default_services()).run(
        arguments.stage, resume=arguments.resume, frozen_model_sha=arguments.frozen_model_sha
    )
    print(json.dumps({"stage": result.stage, "reused_stages": result.reused_stages}, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
