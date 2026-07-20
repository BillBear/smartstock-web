# SH/SZ R1 面板、标签与开发期切分认证

## 结论

`shsz_a_share_v1` 已完成 R1 的新面板、完整前瞻标签和**仅开发期** A/C 切分认证。该资产可以进入
R2 特征质量与 offline/online parity 审计；它不是模型已通过、shadow、paper 或生产接入授权。

本次只新增离线研究资产构建与证据记录。生产候选池、CoachService、选股评分、排序、买卖、止盈止损、
仓位和页面均未修改。

## 不可变资产与来源

| 项目 | 结果 |
| --- | --- |
| SH/SZ R0 universe 契约 | `shsz-universe-contract-v3-iso-date-20260720` |
| R1 面板目录 | `full-market-history-shsz-20260720-v2` |
| 面板行数 / 股票数 / 交易日数 | 2,650,198 / 5,284 / 516 |
| 面板来源 full-build SHA256 | `8d7b105a310edcff293e5a713472486d7be910a5ed0373dd9d4aaab229a5ba4b` |
| universe 契约 SHA256 | `9aef5911d451cf0bf572773b31db3e4bcf9990b0708525afd6d6b145e8a77227` |
| 标签构建代码提交 | `0ac57db` |
| 数据集 ID | `shsz_d41d6245ea81b28f9453` |
| 标签行数 / 股票数 / 信号日数 | 1,845,361 / 5,134 / 377 |
| 标签信号日期 | 2024-11-27 至 2026-06-18 |
| 标签分片 | 64 个 Parquet 分片，约 600 MB |
| 标签质量门禁 | `passed=true` |
| `research_ready` / `production_integration_allowed` | `true` / `false` |

资产位于 Git 外的不可变目录：

```text
$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-shsz-20260720-v2/
$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-development-labels-v1-20260720/
  labels/shard=*/data.parquet
  dataset_registry.json
  development_split_plan.json
  label_objective_report.json
  label_split_manifest.json
  progress.json
```

原始的 `full-market-history-20260718-v2` 旧 feature/dataset parquet 没有被读取或复用；本资产只追溯
其 raw 分区和 full-build manifest。

## 标签与样本质量

标签在收盘后形成信号、以下一交易日开盘作为入口，包含完整的 3/5/10/20 个交易日前瞻收益、路径、
涨跌停和可交易性字段。最终标签行同时要求四个 horizon 均完整，不允许把短窗口样本混入 20 日目标。

| 检查 | 结果 |
| --- | --- |
| `trade_date + symbol` 重复键 | 0 |
| 3/5/10/20 日收益空值 | 各 0 |
| 3/5/10/20 日 horizon 不可用 | 各 0 |
| 每日完整标签数（最小 / 中位 / 最大） | 4,826 / 4,902 / 4,942 |
| 北交所前缀（4/8）标签行 | 0 |
| `alpha_top10_10d` 日占比（最小 / 中位 / 最大） | 9.9814% / 9.9918% / 10.0000% |
| `alpha_top10_10d` 占比标准差 | 0.00005864 |
| 占比与市场中位净收益相关性 | 0.02347 |

标签质量审计没有失败门槛。它只证明标签分布、横截面完整性和来源链条可用于后续研究，**不证明任何特征或
模型具有预测能力**。

## 切分与留出集门禁

开发期按固定种子分为 4,107 只 A（开发训练）股票和 1,027 只 C（开发未见）股票；两个集合不重叠。

五个 expanding walk-forward 折均保留 20 个交易日 embargo。首折在满足
`fit 60 + early-stop 20 + selection 20 + embargo 20` 后才开始验证，避免旧切分中首折无法满足内层
选择合同的问题。

| 折 | 训练日数 | 验证区间 |
| --- | ---: | --- |
| 1 | 100 | 2025-05-29 至 2025-08-08 |
| 2 | 151 | 2025-08-11 至 2025-10-28 |
| 3 | 202 | 2025-10-29 至 2026-01-09 |
| 4 | 253 | 2026-01-12 至 2026-03-31 |
| 5 | 304 | 2026-04-01 至 2026-06-16 |

正式 B/D 时间留出状态固定为：

```json
{
  "status": "awaiting_model_freeze_and_future_labels",
  "minimum_labelable_signal_days": 40,
  "formal_evaluation_allowed": false
}
```

因此，任何人都不能使用这批历史标签选择模型后，再把同一批日期称为最终样本外结果。

## 验证

代码与 focused 测试：

```bash
cd smartstock-web/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_shsz_label_split_asset \
  tests.test_full_market_ml_splits \
  tests.test_full_market_ml_labels \
  tests.test_full_market_ml_ranking_labels
```

观察结果：`Ran 34 tests ... OK`。

完整后端回归：

```bash
git diff --check
cd smartstock-web/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

观察结果：退出码 `0`，`Ran 670 tests in 117.755s`，`OK`。输出含既有 SQLite
`ResourceWarning`；末尾旧候选快照预检仍为 `blocked`，它对应缺少历史 pick snapshots，和本 R1
全市场原始面板资产无关，且本次没有放宽或绕过该旧门禁。

真实资产生成：

```bash
cd smartstock-web/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/build_shsz_label_split_asset.py \
  --panel-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-shsz-20260720-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-development-labels-v1-20260720" \
  --code-commit 0ac57db
```

`progress.json` 最终为 `step=complete`、`failure_type=null`，峰值 RSS 为 2,035,580,928 bytes。

## 下一步与禁止事项

下一步仅允许执行 R2：建立新的特征字典、检查字段覆盖和缺失机制，并对固定日期做 raw -> offline
matrix -> online provider parity。尚不允许训练模型、比较模型、调参、修改生产策略或声称模型改善。

必须保持以下约束：

- 正式时间留出只能在模型冻结后收集至少 40 个新的、可标注信号日时打开。
- R2 若发现未来泄漏、单位不一致、peer set 不一致或覆盖不足，必须停止于特征修复，不能转而训练。
- 当前与历史失败模型继续保持 `research_only_failed_gate`；本资产不会改变它们的状态。
