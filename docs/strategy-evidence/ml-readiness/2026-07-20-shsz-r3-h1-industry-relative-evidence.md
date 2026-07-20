# SH/SZ R3 H1 行业相对特征证据

## 结论

H1 未通过开发期证据门槛，状态为 `research_only_failed_gate`。四个行业相对特征不能进入 ranker 候选，不能训练模型，不能接入 CoachService，也不能改变智能选股、评分、买卖、止盈止损或仓位结果。

这是一条有效的负结论，而不是调参邀请。H1 预先固定为正向等权评分；不能因为结果不佳而在同一开发集上反转方向、改变权重、改变标签或调整阈值。

## 绑定输入

| 项目 | 值 |
| --- | --- |
| 研究宇宙 | `shsz_a_share_v1`，仅 SH/SZ，排除 BJ |
| R1 标签资产 | `shsz_d41d6245ea81b28f9453` |
| R1 标签行数 | 1,845,361 |
| R1 信号日 | 377，2024-11-27 至 2026-06-18 |
| A/C 股票集合 | 4,107 / 1,027，互斥 |
| R2 特征资产 | `shsz-r1-v2-feature-asset-v2-20260720` |
| R2 行数 | 2,546,333，496 个交易日，5,280 只股票 |
| R1 registry SHA256 | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split SHA256 | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 feature manifest payload SHA256 | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| R1 panel manifest SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| 运行器 commit | `4aeeb62` |
| 正式未来时间留出集 | 未开启，`awaiting_model_freeze_and_future_labels` |

运行器逐一校验标签文件和 R2 matrix 文件 SHA256、R1/R2 panel 绑定、五折 A/C membership、SH/SZ universe 和 Hive schema。R2 manifest 的 staging `matrix_path` 已不可用；运行器只允许回退到同一资产根目录的固定 `matrix/`，仍受逐文件 SHA256 约束。

## 固定假设

只检验一个问题：下列四个已注册行业相对字段的每日截面正向百分位排名等权平均，是否优于 `adjusted_return_60d` baseline。

- `industry_return_5d_rank`
- `industry_return_5d_excess`
- `industry_return_20d_rank`
- `industry_return_20d_excess`

标签与执行口径固定为：`alpha_relevance_grade_10d`、`alpha_top10_10d`、`alpha_target_10d`、`net_return_after_cost_10d`、`severe_negative_10d`，以及下一交易日进入的 R1 `entry_price` / `exit_price` / `exit_trade_date`。成本和滑点由共享组合模拟器按 commission `0.0003`、slippage `0.001` 执行。

没有训练、网格搜索、特征筛选、校准或参数优化。市场状态在 R2 中没有 materialized `market_context`，报告为 `unavailable`，没有用代理变量补造市场状态。

## 结果

正式产物：

`/Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h1-industry-relative-evidence-20260720-r4`

### 特征审计

四个特征的最小折覆盖率为 `98.99%` 至 `99.46%`，所以失败不是由缺失率造成。相反，前四个开发折的 10 日 alpha IC 为负：20 日字段约 `-0.0245` 至 `-0.0683`，5 日字段约 `-0.0250` 至 `-0.0499`；仅第 5 折转为正。固定正向 H1 没有跨市场阶段的稳定性。

### 五折门槛

| 门槛 | 要求 | 实际 | 结果 |
| --- | --- | --- | --- |
| A 开发已见股票 | 至少 4/5 折同时不差于 baseline 的 P@5、NDCG@10、Top5 净收益，P@5 uplift 95% CI 下界大于 0，回撤不差且有闭环交易 | 1/5 | 失败 |
| C 开发未见股票 | 至少 4/5 折 NDCG@10 不低于 baseline 0.02 以上 | 2/5 | 失败 |
| Bootstrap | A 折 P@5 uplift 95% CI 下界大于 0 | 仅第 4 折为 `+0.0706`；其余为负 | 失败 |
| 风险路径 | 不得掩盖严重负向风险 | H1 多折 Top5 severe-negative rate 高于 baseline，例如 A 折 1 为 `82.75%` 对 `58.04%` | 不支持候选 |

代表性 A 折：

| 折 | H1 / baseline P@5 | H1 / baseline NDCG@10 | H1 / baseline Top5 净收益 | 结论 |
| --- | --- | --- | --- |
| 1 | 0.2353 / 0.3176 | 0.2295 / 0.2910 | -0.51% / +5.78% | 明显落后 |
| 2 | 0.2353 / 0.2196 | 0.2303 / 0.2131 | -1.92% / -2.35% | bootstrap 不通过 |
| 3 | 0.2588 / 0.2235 | 0.2262 / 0.1833 | -0.46% / -0.79% | bootstrap 不通过 |
| 4 | 0.2784 / 0.1176 | 0.2433 / 0.1318 | -2.29% / -8.05% | 唯一通过折 |
| 5 | 0.3490 / 0.3765 | 0.3186 / 0.3576 | +3.68% / +8.75% | 明显落后 |

完整每折指标、bootstrap、组合路径、预测和特征审计分别在运行目录的 `fold_metrics.json`、`predictions.parquet`、`feature_*.csv`、`candidate_screen.json` 和 `h1_feature_evidence.json` 中。它们是本地研究资产，不提交 Git。

## 工程修复记录

本次正式运行前发现并修复三个工程问题：

1. R2 原子提升后 manifest 仍指向失效 staging `matrix_path`。限制回退到同资产根目录 `matrix/`，逐文件 SHA256 继续验证。
2. 标签日期和代码逐行调用 pandas 规范化，1,845,361 行会产生数分钟无心跳。改为向量化规范化，并测试 `20250102` 与 `2025-01-02` 混用、空 symbol 和 `.BJ` 拒绝。
3. 共享 evaluator 只识别旧名 `label_severe_negative_10d`。H1 运行器保留 R1 canonical `severe_negative_10d` 并提供值相同的只读别名，避免风险率被错误记为 0。

## 验证

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-36-shsz-h1-feature-evidence/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest tests.test_shsz_h1_feature_evidence -v
```

关键输出：6 项 H1 针对性测试通过。

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h1_feature_evidence.py \
  --label-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-development-labels-v1-20260720 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/derivations/shsz-r1-v2-feature-asset-v2-20260720 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/shsz-r3-h1-industry-relative-evidence-20260720-r4 \
  --code-commit 4aeeb62 --bootstrap-iterations 1000
```

关键输出：`status=complete`，`candidate_status=research_only_failed_gate`。

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-36-shsz-h1-feature-evidence/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  -m unittest discover -s tests -q
```

关键输出：`Ran 683 tests in 129.971s`，退出码 `0`。既有 suite 的 SQLite `ResourceWarning` 和末尾 snapshot preflight `status: blocked` 是历史测试输出，不是本次 H1 的失败退出。

## 后续边界

H1 失败只拒绝这个固定行业相对特征组。后续 H2/H3 必须新建独立计划和 worktree，预注册单一假设，不能继承、反转或重调 H1。正式未来时间留出集继续封存，任何生产策略改变仍需要独立 baseline、样本外和 walk-forward 证据。
