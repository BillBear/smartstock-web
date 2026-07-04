# SmartStock Recall Experiment Current Readiness

生成时间：2026-07-04

## 结论

当前已有离线召回实验比较器，但还没有真实的宽召回实验组输入。因此，本阶段不能切换生产召回、深度分析数量或多通道召回逻辑。

- 状态：`blocked`
- 生产切换：`false`
- 已有实验报告：`1 / 5`
- 可用实验：`baseline`
- 缺失实验：`recall_220_deep_150`、`recall_300_deep_300`、`recall_500_deep_500`、`multi_channel_union`
- 阻塞原因：`missing_experiment_reports`、`no_variant_passed_gates`

这说明当前只具备“比较实验结果”的工具，不具备“证明宽召回更优”的证据。

## 输入

本次只使用最新真实 ranking baseline 摘要作为 baseline 输入：

```text
docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_summary.json
```

该运行产物属于本地证据产物，默认不提交；本文档只记录关键摘要。

## 复现命令

```bash
cd smartstock-web
rm -rf /tmp/smartstock-recall-experiment-current
mkdir -p /tmp/smartstock-recall-experiment-current/baseline
cp docs/strategy-evidence/ranking-evaluation/runs/trend_breakout-medium-2026-04-28-2026-07-03-20260703223857/ranking_summary.json \
  /tmp/smartstock-recall-experiment-current/baseline/ranking_summary.json

cd backend
source venv/bin/activate
python scripts/run_recall_experiment.py \
  --experiment-root /tmp/smartstock-recall-experiment-current \
  --output-json /tmp/smartstock-recall-experiment-current-report.json \
  --output-md /tmp/smartstock-recall-experiment-current-report.md
```

关键输出：

```text
wrote json: /tmp/smartstock-recall-experiment-current-report.json
wrote markdown: /tmp/smartstock-recall-experiment-current-report.md
status: blocked
production_switch_ready: False
```

## Baseline 摘要

```text
candidate_row_count: 635
coverage_status: partial
covered_date_count: 22
requested_date_count: 49
evidence_status: insufficient
production_evidence: false
recall_size: 220
deep_analysis_size: 72
recall_method: production_pre_score
```

指标：

```text
Precision@3: 0.132184
Precision@5: 0.151724
NDCG@10: 0.275454
Top5 average return pct: 0.099766
max_drawdown: 0.0
```

## 影响判断

本次只运行离线比较器并记录当前缺口，不修改生产选股、召回、排序、买入、卖出、止盈、止损或仓位逻辑。

下一步若要推进 Phase 5，必须先生成四个离线实验组的真实 ranking summaries，并确保它们和 baseline 使用同一区间、同一标签、同一交易成本与滑点口径。只有实验组通过门禁后，才允许提出独立的策略切换方案。
