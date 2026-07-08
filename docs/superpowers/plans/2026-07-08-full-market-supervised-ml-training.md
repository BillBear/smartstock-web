# Full Market Supervised ML Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent TuShare full-market supervised ML training pipeline that collects historical all-A-share panels, builds leak-free features and forward labels, trains research-only models, and validates full-market TopK performance.

**Architecture:** Add read-only evaluation modules and CLIs under `backend/app/evaluation` and `backend/scripts`. Runtime data and model artifacts are written under `runtime/ml_full_market/` and never committed. Production SmartStock selection, ranking, buy/sell, take-profit, stop-loss, and position sizing logic remain untouched.

**Tech Stack:** Python 3, pandas, pyarrow-backed parquet files, scikit-learn/joblib, optional LightGBM/XGBoost only when installed, unittest.

## Global Constraints

- Do not modify production stock selection, ranking, buy/sell, take-profit, stop-loss, or position sizing logic.
- Do not change production strategy parameters.
- The new model remains `research_only` or `shadow_candidate` until separate production integration is approved.
- Full-market training must never fall back to candidate snapshots.
- Feature columns must not include future or label fields.
- Runtime raw panels, model artifacts, local secrets, and cache files must not be committed.

---

## Tasks

1. Add full-market panel collection and manifest support with TuShare endpoint fixtures.
2. Add panel normalization, sample quality gates, and trainability blocking when full-market coverage is insufficient.
3. Add forward label builder for 3/5/10/20 day returns, Top/Bottom daily ranks, TP/SL path,涨跌停 counts, and entry tradability.
4. Add feature builder with explicit leak-free feature schema and feature dictionary.
5. Add TopK evaluator and split-aware trainer that compares models against `adj_return_60d_rank` and never enables production.
6. Add CLI entrypoints for collection, dataset build, and experiment runs.
7. Add strategy evidence documentation and final verification.

## Verification

- `git diff --check`
- `cd backend && python3 -m unittest tests.test_full_market_ml_pipeline -v`
- `cd backend && python3 -m unittest discover -s tests`
- `cd backend && python3 scripts/collect_full_market_training_panel.py --start-date 2026-01-02 --end-date 2026-01-05 --dry-run`
- `cd backend && python3 scripts/run_full_market_ml_experiment.py --panel-dir ../runtime/ml_full_market/smoke/panel --output-dir ../runtime/ml_full_market/runs/smoke --smoke`

