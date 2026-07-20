# SH/SZ R3-H1 行业相对强度特征证据实施计划

> **For agentic workers:** 使用本会话内联执行。用户明确禁止子智能体；每个任务使用独立 worktree、TDD、代码审查和独立提交。

**Goal:** 在不训练模型、不打开未来时间 holdout、不改变生产策略的前提下，验证 R2 中已注册的行业内相对强度特征是否能在 R1 sealed A/C development folds 中稳定提升 Top-K 排序质量。

**Architecture:** R1 标签资产与 R2 特征资产保持物理分离。新的只读 H1 runner 先验证二者的 SHA256 绑定，再按 `(trade_date, symbol)` 只连接 H1 所需特征、固定 baseline 和评估标签；所有方向、比较器、成本与拒绝门槛在运行前写死。结果仅保存在 Git 外的 evidence run，并以 CSV/JSON/Markdown 记录。

**Tech Stack:** Python 3.13、Pandas、PyArrow、现有 `feature_audit.py`、`evaluator.py`、`DevelopmentOnlySplitPlan`、`unittest`。

## 全局约束

- 研究 universe 固定为 `shsz_a_share_v1`，仅 `.SH` / `.SZ`，不补回北交所。
- 输入固定为 R1 标签资产 `shsz-r1-v2-development-labels-v1-20260720` 和 R2 v2 特征资产 `shsz-r1-v2-feature-asset-v2-20260720`；v1 特征资产禁止读取。
- 禁止读取、训练或调优正式未来时间 holdout；`future_holdout.status` 必须保持 `awaiting_model_freeze_and_future_labels`。
- 禁止变更生产选股、排序、评分、买卖、止盈止损、仓位、CoachService、API 或前端。
- H1 仅评估已经 materialize 的 `industry_relative` 组；R2 没有注册 `market_context`，市场状态实验必须报告 `unavailable`，不得用代理变量伪造。
- 任何 H1 结论均为 `research_only`，即使开发期门槛通过也不能训练 ranker 或接入生产。
- 运行产物、Parquet、预测和模型文件不提交 Git；Git 只提交代码、测试、计划和结论文档。

## 固定输入、标签与比较器

### 资产绑定

| 项目 | 固定值 |
| --- | --- |
| R1 panel manifest SHA256 | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| R1 label registry SHA256 | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| R1 split SHA256 | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| R2 feature manifest SHA256 | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |
| R2 feature contract | `shsz_r1_detailed_moneyflow_parity_v1`，111 个特征 |
| Development split | 5 个 walk-forward fold、20 个交易日 embargo、A/C 股票集合互斥 |

Runner 必须重新计算本地 JSON/Parquet manifest 引用的 SHA256；任一不一致、任一 R2
`production_integration_allowed=true`、任一 `.BJ` 行、任一重复 key 或标签/特征 key 不相等时终止。

### H1 特征和方向

H1 只使用以下 4 个 R2 已注册字段，方向预注册为 `+1`，不得由验证标签反推：

```text
industry_return_5d_rank
industry_return_5d_excess
industry_return_20d_rank
industry_return_20d_excess
```

每个交易日，H1 分数为这四列各自在可比较股票集合中的百分位 rank 的算术平均；缺任一 H1
字段或 baseline 字段的行从**所有**比较器同时剔除。固定 baseline 为
`adjusted_return_60d`，分数直接使用该列。不得测试反向分数、不同窗口、加权组合、阈值或额外
特征。

### 标签和执行口径

| 用途 | R1 列 |
| --- | --- |
| 排序 relevance | `alpha_relevance_grade_10d` |
| Precision@K 正类 | `alpha_top10_10d` |
| Top-K 经济结果 | `net_return_after_cost_10d` |
| 连续 alpha 诊断 | `alpha_target_10d` |
| 风险诊断 | `severe_negative_10d` |
| 执行模拟 | `entry_price`、`exit_price`、`exit_trade_date`、`entry_tradeable`、`path_ambiguous_10d` |

信号为收盘后，入场为下一交易日开盘；模拟成本固定为双边 commission `0.0003` 和 slippage
`0.001`，持有 10 个交易日。所有比较器必须使用同一 `(trade_date, symbol, risk_eligible)` key
集合。

## 预注册门槛与拒绝标准

H1 的结果分为“单变量质量”和“组排序证据”，两者均需记录，且不允许以其中一个替代另一个。

### 单变量质量

对每个 H1 特征、每个 A fold validation 日期计算每日 Spearman IC 与五分位
`alpha_target_10d` spread。字段可进入 H1 组证据的最低要求：

- 五折最低覆盖率 `>= 0.95`；
- 至少 4/5 fold 的 median IC 同号；
- 至少 4/5 fold 的 top-bottom alpha spread 与预注册正方向一致；
- 相邻 fold PSI 不得有超过 2 个 `> 0.25` 的记录；
- 任一特征不通过只记录为 `excluded`，不得改变其方向或窗口重新尝试。

### H1 组排序证据

按每个 fold、每个 A/C 象限分别计算 `Precision@3/5/10`、`NDCG@10`、`MRR`、Top5
`net_return_after_cost_10d`、Top5 severe-negative 率、模拟组合最大回撤、收益回撤比和闭环交易数。
Bootstrap 按完整交易日 circular block 重采样，固定 `iterations=1000`、`seed=42+fold`、
`block_length=10`，只重采样预先算好的日度指标。

H1 只有同时满足下列要求才获得 `development_feature_group_candidate`，否则为
`research_only_failed_gate`：

1. A 中至少 4/5 fold：H1 的 `Precision@5`、`NDCG@10` 和 Top5 净收益均不低于
   `adjusted_return_60d` baseline；
2. A 中至少 4/5 fold：Precision@5 uplift bootstrap 95% 下界 `> 0`；
3. A 中至少 4/5 fold：最大回撤不劣于 baseline，且闭环交易数大于 0；
4. C 中至少 4/5 fold：`NDCG@10 >= baseline - 0.02`，不能出现未见股票崩塌；
5. H1 分数不存在任何 label、future、next-open、执行结果字段依赖；
6. 无论通过与否，`production_integration_allowed=false`。

## 任务分解

### Task 1: 为既有 feature audit 增加显式主目标

**Files:**
- Modify: `backend/app/evaluation/full_market_ml/feature_audit.py`
- Modify: `backend/tests/test_full_market_ml_feature_audit.py`

**接口:**

```python
def audit_features(
    development_dataset: pd.DataFrame,
    split_plan: SplitPlan,
    *,
    feature_schema: Iterable[str] | None = None,
    primary_target: str | None = None,
    on_progress: Callable[[Mapping[str, object]], None] | None = None,
) -> FeatureAuditResult:
```

- [ ] 写失败测试：包含 `alpha_target_10d` 和 `net_return_after_cost_10d` 的 fixture 传入
  `primary_target="alpha_target_10d"` 后，IC 和 bucket report 的主 target 必须是
  `alpha_target_10d`；未提供该列必须抛出明确 `ValueError`。
- [ ] 运行单测，确认当前实现错误地选择 `net_return_after_cost_10d`。
- [ ] 实现：当 `primary_target` 非空时只允许现有、非泄漏、数值标签列；继续附加已注册风险标签，
  不改变默认调用的旧选择逻辑。
- [ ] 运行相关单测及完整后端测试。
- [ ] 独立提交：`feat(ml): support explicit feature-audit target`。

### Task 2: 构建 R1/R2 受绑定的 H1 行业相对强度 runner

**Files:**
- Create: `backend/app/evaluation/full_market_ml/shsz_h1_feature_evidence.py`
- Create: `backend/scripts/run_shsz_h1_feature_evidence.py`
- Create: `backend/tests/test_shsz_h1_feature_evidence.py`

**接口:**

```python
def run_shsz_h1_feature_evidence(
    *,
    label_root: str | Path,
    feature_asset_root: str | Path,
    output_dir: str | Path,
    code_commit: str,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
```

- [ ] 写失败 fixture：manifest 哈希不匹配、v1 路径、`.BJ` symbol、重复 key、缺失 H1 字段、
  label/feature join 不完整、尝试读取 future holdout，均须在读标签值前终止。
- [ ] 写失败 fixture：候选 H1 与 baseline 比较器 key 不一致时，
  `validate_identical_comparison_rows` 必须拒绝运行。
- [ ] 运行 fixture，确认 runner 尚不存在。
- [ ] 实现输入验证：读取 R1 `dataset_registry.json`、`development_split_plan.json`、
  `label_split_manifest.json` 和 R2 `feature_asset_manifest.json`；只接受 R2 `status=complete`、
  `research_ready=true`、`production_integration_allowed=false`、正确 panel/split/registry 哈希和
  `future_holdout.status=awaiting_model_freeze_and_future_labels`。
- [ ] 实现最小列连接：标签只读 Task 1 表中列，R2 每日分区只读 4 个 H1 字段与
  `adjusted_return_60d`。连接后强制 1:1 key、377 个 label signal dates、无 `.BJ`、无 duplicate
  keys；不将标签写入 R2 资产。
- [ ] 实现 A/C 五折评估：固定正向日截面 rank 平均 H1 分数与固定 baseline，分别输出
  `fold_<n>_A_development_seen`、`fold_<n>_C_development_unseen` 的 metrics、bootstrap、portfolio
  和 feature audit。
- [ ] 实现资产：`input_manifest.json`、`progress.json`、`feature_coverage.csv`、
  `feature_ic.csv`、`feature_bucket_returns.csv`、`feature_correlation.csv`、`feature_drift.csv`、
  `fold_metrics.json`、`bootstrap.json`、`portfolio_metrics.json`、`candidate_screen.json`、
  `predictions.parquet`、`run_manifest.json`、`model_card.md`。`model_card.md` 必须声明“无模型”。
- [ ] 运行 fixture 单测、CLI smoke 和完整后端测试。
- [ ] 独立提交：`feat(ml): audit SHSZ H1 industry-relative evidence`。

### Task 3: 运行真实 H1 证据并作只读验收

**Files:**
- Runtime only: `$SMARTSTOCK_ML_ASSET_ROOT/runs/shsz-r3-h1-industry-relative-YYYYMMDD/`
- Create: `docs/strategy-evidence/ml-readiness/YYYY-MM-DD-shsz-r3-h1-industry-relative-result.md`
- Modify: `docs/strategy-evidence/ml-readiness/current-readiness.md`
- Modify: `docs/strategy-evidence/ml-readiness/README.md`

- [ ] 创建空输出目录；先运行 CLI `--smoke`，确认不访问未来 holdout、production 或 CoachService。
- [ ] 正式运行固定 R1/R2 输入和 1000 次 bootstrap，定期读取 `progress.json`；阶段超过预算或
  5 分钟无心跳则写 `timeout`，停止且不写成功结论。
- [ ] 对输出复算：所有 manifest SHA、prediction keys、A/C disjointness、fold 日期属于 sealed
  development、comparison keys、3/5/10 Top-K 指标、成本/滑点、max drawdown 与 return/drawdown。
- [ ] 生成结论文档：逐 fold 表格、A/C 对比、通过/失败门槛、负结论、运行命令、运行时间与磁盘占用。
- [ ] 更新 current readiness：只有 H1 `research_only` 结果；禁止把开发期通过写成模型通过或生产就绪。
- [ ] 文档单独提交：`docs(ml): record SHSZ R3 H1 evidence`。

## 执行验证

```bash
cd smartstock-web/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_feature_audit \
  tests.test_shsz_h1_feature_evidence

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_shsz_h1_feature_evidence.py \
  --label-root "$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-development-labels-v1-20260720" \
  --feature-asset-root "$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-feature-asset-v2-20260720" \
  --output-dir /tmp/shsz-r3-h1-smoke \
  --code-commit "$(git rev-parse --short HEAD)" \
  --bootstrap-iterations 3 \
  --smoke

git diff --check
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

## 计划自检

- 数据、标签、特征、split、目标、比较器、成本、bootstrap、A/C 样本外、拒绝门槛和产物均有明确任务。
- 未使用候选池快照、新闻分、北交所、未来 holdout 或生产策略字段。
- 计划没有任何“试多个阈值”“换模型看看”步骤；H1 失败时直接记录失败，不进入 ranker。
- H2 详细资金流、H3 公告时点基本面和任何模型训练均不属于本计划；它们只能在 H1 结案后以新的、独立的预注册计划处理，不能复用 H1 的调参或门槛。
