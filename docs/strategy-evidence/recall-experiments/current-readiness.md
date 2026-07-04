# SmartStock Recall Experiment Current Readiness

生成时间：2026-07-04

## 结论

当前已有离线召回实验比较器、只读离线召回候选生成器，并已完成一轮同口径全区间真实宽召回实验。但实验组没有通过生产切换门禁。因此，本阶段不能切换生产召回、深度分析数量或多通道召回逻辑。

- 状态：`blocked`
- 生产切换：`false`
- 已有能力：`baseline replay`、`offline variant generator`、`experiment comparator`、`snapshot-backed forward labels`
- 已有正式实验报告：`5 / 5`
- 可用实验：`baseline`、`recall_220_deep_150`、`recall_300_deep_300`、`recall_500_deep_500`、`multi_channel_union`
- 缺失实验：无
- 阻塞原因：`no_variant_passed_gates`

这说明当前已经具备“生成离线实验候选”和“比较实验结果”的工具，但最新证据不支持把宽召回或多通道召回切入生产。

2026-07-04 后新增的只读生成器：

```text
backend/scripts/run_offline_recall_evaluation.py
backend/app/evaluation/offline_recall_candidates.py
backend/app/evaluation/market_snapshot_history.py
```

该生成器只读取已保存的全 A 市场快照和 forward label 历史。标签读取优先使用持久化 `market_snapshots` / `market_snapshot_items`，本地快照缺失时才 fallback 到显式远端历史行情窗口。它只输出 ranking evaluation 产物；不写入候选池、不刷新策略、不改变生产排序、买入、卖出、止盈止损或仓位逻辑。

2026-07-04 后新增的比较门禁：即使五个实验报告都存在，也必须和 baseline 使用相同的 `strategy_code`、`risk_level`、起止日期、horizon、Top-K、标签配置、交易成本和滑点配置。任一可用实验组口径不一致时，比较器会返回 `incompatible_experiment_reports`，并禁止给出生产切换结论。

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

只读生成离线实验组的命令：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-04-28 \
  --end-date 2026-07-03 \
  --horizons 3,5,10,20 \
  --top-k 3,5,10 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-offline-recall-experiment
```

注意：该命令可能需要较长时间。当前脚本会先按显式日期范围读取本地持久化市场快照，缺失时才走远端历史行情 fallback。生成结果仍必须经过 `recall_experiment_report.json` 的门禁判断，不能直接用于生产切换。

## 本轮工具验证

CLI smoke 验证：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-01-02 \
  --end-date 2026-01-09 \
  --horizons 3,5 \
  --top-k 3,5 \
  --experiment-key recall_220_deep_150 \
  --experiment-key multi_channel_union \
  --output-root /tmp/smartstock-offline-recall-smoke \
  --fixture smoke
```

关键输出：

```text
generated recall_220_deep_150: fixture smoke
generated multi_channel_union: fixture smoke
comparison_status: blocked
production_switch_ready: False
```

真实数据极小范围管线验证：

```bash
cd smartstock-web/backend
source venv/bin/activate
python scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-05-29 \
  --end-date 2026-05-29 \
  --horizons 3 \
  --top-k 3 \
  --experiment-key recall_220_deep_150 \
  --max-rows-per-day 2 \
  --output-root /tmp/smartstock-offline-recall-real-smoke
```

关键输出：

```text
TuShare服务: 已启用
candidate_rows: 2
coverage_status: complete
covered_date_count: 1
evidence_type: real_insufficient
production_evidence: false
comparison_status: blocked
blocking_reasons: missing_experiment_reports,baseline_report_missing,no_variant_passed_gates
```

该真实小跑只验证管线，不是策略证据；它覆盖 1 个日期、2 个候选，远低于生产准入要求。

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
Precision@3: 0.160000
Precision@5: 0.132000
NDCG@10: 0.242221
Top5 average return pct: -1.525033
max_drawdown: 0.0
```

最新离线实验摘要：

```text
recall_220_deep_150 Precision@3: 0.264957, Precision@5: 0.251282, NDCG@10: 0.153053, Top5 average return pct: 1.755358
recall_300_deep_300 Precision@3: 0.264957, Precision@5: 0.251282, NDCG@10: 0.137071, Top5 average return pct: 1.755358
recall_500_deep_500 Precision@3: 0.264957, Precision@5: 0.251282, NDCG@10: 0.128966, Top5 average return pct: 1.755358
multi_channel_union Precision@3: 0.256410, Precision@5: 0.225641, NDCG@10: 0.146095, Top5 average return pct: 3.082375
```

标签质量摘要：

```text
missing_history: 0
baseline tradable labels: 634 / 635
recall_220_deep_150 tradable labels: 2693 / 2700
recall_300_deep_300 tradable labels: 5388 / 5400
recall_500_deep_500 tradable labels: 8975 / 9000
multi_channel_union tradable labels: 4762 / 4776
```

## 影响判断

本次只运行离线比较器并记录当前缺口，不修改生产选股、召回、排序、买入、卖出、止盈、止损或仓位逻辑。

下一步若要推进 Phase 5，需要积累或回填至少 30 个同口径全市场快照日期，并在覆盖达标后重新跑同一矩阵。只有实验组通过 Precision/NDCG/收益/回撤门禁后，才允许提出独立的策略切换方案。
