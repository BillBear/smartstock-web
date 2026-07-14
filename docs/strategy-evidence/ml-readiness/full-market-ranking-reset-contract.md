# Full-Market Ranking Reset Contract

## Status

- Run ID: `ml_ranking_reset_20260714_v1`
- Dataset ID: `fmv3_ea0797d57ed62a916b3a`
- Production integration: prohibited
- Future holdout: sealed
- Primary objective: daily cross-sectional 10-session net excess-return ranking
- Separate objective: absolute severe downside/path risk

## Immutable Decisions

- Signals use information available after the A-share close.
- Entry is the next exact trading-session open after tradability checks.
- The holding horizon is 10 trading sessions.
- Commission is `0.0003` per side and slippage is `0.001` per side.
- Stocks require at least 120 completed trading sessions.
- Five outer walk-forward folds use a 20-session embargo.
- Inner fit, early-stop, and selection roles require at least 60, 20, and 20 dates and may not overlap.
- Required baselines are random, 20-day momentum, 60-day momentum, amount ascending, amount descending, and one registered single feature.
- Allowed learned families are a linear scorecard and shallow LightGBM LambdaRank.
- Model features are capped at 60.
- Process RSS has a 12 GB soft limit and a 13 GB abort limit.

## Evidence Status Semantics

- `engineering_valid`: the stage ran and its artifact hashes verify.
- `research_design_valid`: measured inputs satisfy the frozen research contract.
- `model_gate_passed`: a frozen development candidate passed every pre-registered A/C gate.
- `production_candidate`: a frozen candidate later passed an untouched future holdout.

These fields are independent. Stage completion does not imply research validity or model acceptance.

## Local Artifact Policy

Runtime data and model binaries remain under `/Users/xiong/Documents/SmartStock/ml-assets/`. At closure, rebuildable process artifacts are archived as `tar.gz`, the archive is SHA256-verified, and only files declared rebuildable may be deleted. Immutable source partitions, final compact datasets, OOF predictions, manifests, metrics, and model cards remain available for audit.
