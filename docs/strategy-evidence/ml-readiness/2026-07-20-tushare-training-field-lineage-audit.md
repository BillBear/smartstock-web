# TuShare 训练字段血缘审计

## 结论摘要

**结论：`pipeline_lineage_gap`，不得把当前资金流细分特征视为已经被训练或验证。**

当前 TuShare 权限和原始两年历史分区均可获得订单大小维度的资金流字段。问题发生在不可变训练资产的 `raw -> frozen dataset` 边界：八个买卖金额字段没有被保留进 `fmv3_ea0797d57ed62a916b3a` 的 `dataset-v3`。因此，`ml_ranking_reset_20260714_v4` 的矩阵虽有五个细分派生列名，值却全部为空。

这不是模型好坏或特征有效性的证据。它只是说明此前的“细分资金流 0% 覆盖”不能归因于 TuShare token、接口权限或原始数据缺失。当前模型状态仍为 `research_only_failed_gate`，没有任何生产选股、排序、评分、买卖或前端决策改动。

## 审计范围

- 审计日期：2026-07-20
- 代码分支：`research/tushare-training-coverage-audit`
- 审计代码提交：`509dacb`、`e5a1f59`、`40fb27b`
- 原始资产：`raw_80ec15845c4574cd`
- 冻结数据集：`fmv3_ea0797d57ed62a916b3a`
- 矩阵资产：`ml_ranking_reset_20260714_v4`
- 抽样交易日：2024-06-03、2025-07-02、2026-07-10

本任务只读取 immutable Parquet 资产并写入独立运行产物。没有重拉两年历史、没有重建数据集、没有写数据库、没有读取或输出 token。

## 资产身份与复现产物

| 对象 | 路径 | SHA256 |
| --- | --- | --- |
| 原始资产清单 | `ml-assets/raw/raw_80ec15845c4574cd/source_manifest.json` | `ee018a4a6dca5997f6a26fdf741b0d5e80e63ceb50853df8d1c732f68ff9542b` |
| 冻结数据集注册表 | `ml-assets/datasets/fmv3_ea0797d57ed62a916b3a/artifacts/full-build/dataset_registry_v3.json` | `af05ae7edbf85e509d523593bf5f0430c5dbd30125d9afecf888afa1266c9e70` |
| 现有特征矩阵清单 | `ml-assets/runs/ml_ranking_reset_20260714_v4/artifacts/feature-evidence/feature_matrix_manifest.json` | `45e2d8b543205960f31c030b704e14a262ac6604d9aa4091ae6f50d70d71af8f` |
| 本次血缘报告 | `ml-assets/runs/tushare-training-field-lineage-audit-20260720/lineage_report.json` | `b982c50f5a5465621897aa90cd9ec59c49f1f2ff77f200755613a48b5fb5d156` |
| 本次字段覆盖 CSV | `ml-assets/runs/tushare-training-field-lineage-audit-20260720/field_coverage.csv` | `477610b4d1c2949dc63954fd006f1daed44fc552191a6043955065333af96747` |
| 脱敏 TuShare 能力报告 | `ml-assets/runs/tushare-training-field-lineage-audit-20260720/tushare_history_probe.json` | `a7a8cc0397b0d8536230a9ffaf309eb3ce6c170ba4a96ea8937149ac5f30df5c` |

原始清单对三个资金流分区声明的 SHA256 分别为：

- 2024-06-03：`348ff7a2285e335ccf0beb88c3ab403786514c9f8e00d61ab9fab9f678840884`
- 2025-07-02：`99bd90254d68043eb1ccbf9cf05fc9142700e313e2b43869391e2648701877c9`
- 2026-07-10：`49295ed928866e666b42b9348bc001f5ddb7352ae089853a9e3802f646a7acb6`

运行产物不提交 Git，保留在本地 `ml-assets/runs/`，可按上表的输入路径和命令重新生成。

## 当前 Token 能力

使用现有本地 secret 的受限探针覆盖 511 个交易日范围的首尾两个交易日。它没有输出 token。

| 接口 | 状态 | 两日样本行数 | 唯一证券数 | 日期覆盖 |
| --- | --- | ---: | ---: | --- |
| `moneyflow` | `valid_with_rows` | 10,285 | 5,270 | 2/2 |
| `daily_basic` | `valid_with_rows` | 10,862 | 5,598 | 2/2 |
| `adj_factor` | `valid_with_rows` | 10,925 | 5,640 | 2/2 |
| `stk_limit` | `valid_with_rows` | 14,509 | 7,824 | 2/2 |
| `index_daily` | `valid_with_rows` | 2 | 1 | 2/2 |

`stock_basic` 也返回 5,866 行，历史上市/退市区间契约通过。该结果证明当前 token 可用于后续独立的数据重建任务，但不等价于任何因子的预测能力。

## 字段血缘结果

审计字段为 `buy_sm_amount`、`sell_sm_amount`、`buy_md_amount`、`sell_md_amount`、`buy_lg_amount`、`sell_lg_amount`、`buy_elg_amount`、`sell_elg_amount`。

| 阶段 | 抽样行数 | 八个原始字段状态 | 覆盖率 |
| --- | ---: | --- | --- |
| TuShare raw `moneyflow` | 15,421 | 全部存在 | 每列 100% |
| 冻结 `dataset-v3` | 16,264 | 全部缺少于 schema | 每列 0% |
| 特征矩阵 | 4,929 | 五个派生列名存在，但数值均为空 | 每列 0% |

五个受影响派生特征均被判定为 `raw_to_dataset_gap`：

- `medium_net_flow_persistence_20d`
- `large_net_flow_persistence_20d`
- `price_flow_divergence_5d`
- `price_flow_divergence_20d`
- `flow_minus_industry_median`

矩阵中仅包含 2025-07-02，是因为该矩阵只保留研究开发期，2024-06-03 仍处在特征预热区间，2026-07-10 属于封存时间留出区间。这不会影响本次根因判断：细分原始字段在冻结数据集之前已经丢失，矩阵无法重新生成它们。

## 代码与证据边界

- [`panel.py`](/Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend/app/evaluation/full_market_ml/panel.py:25) 的允许字段和 join 逻辑支持这些字段。
- [`moneyflow_features.py`](/Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend/app/evaluation/full_market_ml/moneyflow_features.py:24) 在八个字段都已提供时可以生成细分特征。
- [`feature_stage.py`](/Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend/app/evaluation/full_market_ml/feature_stage.py:83) 只能读取冻结数据集中实际存在的列，不能从 raw 资产重新恢复已丢失的字段。

历史 `fmv3` 没有保留 panel 资产。因此可以严格证明的丢失边界是 `raw -> frozen dataset`，不能仅凭当前代码断言具体是当时的 panel 写出、特征构造还是 dataset 序列化函数造成。把这个不确定性写清楚，比事后臆测根因更可靠。

## 验证记录

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-18-tushare-training-coverage-audit/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_tushare_training_field_lineage_audit \
  tests.test_run_tushare_training_field_lineage_audit \
  tests.test_full_market_ml_tushare_history_probe
```

实际输出：`Ran 15 tests ... OK`。

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/run_tushare_training_field_lineage_audit.py \
  --raw-root /Users/xiong/Documents/SmartStock/ml-assets/raw/raw_80ec15845c4574cd \
  --dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fmv3_ea0797d57ed62a916b3a \
  --matrix-root /Users/xiong/Documents/SmartStock/ml-assets/runs/ml_ranking_reset_20260714_v4/artifacts/feature-evidence/matrix \
  --sample-dates 2024-06-03,2025-07-02,2026-07-10 \
  --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/tushare-training-field-lineage-audit-20260720
```

实际输出：`overall_verdict=pipeline_lineage_gap`，`production_integration_allowed=false`。

```bash
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests
```

实际输出：`Ran 643 tests in 103.414s`，`OK`，退出码 `0`。测试过程中有既有 SQLite `ResourceWarning`。末尾的 ML 预检仍输出 `status: blocked`，原因是可用全市场快照数量、股票数量、日期数量和样本数均未达到门槛；该预检没有被本次改动修改、放宽或绕过。

`git diff --check` 也已通过。

## 对抗性审查与下一道门

已检查的误判风险：

- 日期同时接受 `YYYYMMDD` 和 `YYYY-MM-DD`，避免字符串格式造成假阴性。
- raw 和 dataset 的行数不同不会被误读为字段缺失；判断依据是 schema 与非空覆盖，而不是行数相等。
- 不把三日抽样覆盖率冒充两年全量覆盖率；当前结论只对抽样和 schema 边界成立。
- 没有把“字段可获得”写成“特征有效”或“模型可接入”。
- 没有重用或打开原 final holdout，也没有触碰当前生产策略。

下一项工作必须在新的独立 worktree 完成：以同一 raw asset 构建一个新的、版本化的**离线候选数据集**，显式保留八个原始字段，并先做完整的数据质量、点时性、缺失率、日期/证券键唯一性和特征 parity 测试。只有通过这些前置门槛，才能在开发期训练数据上进行一次固定假设的、train-only OOF 细分资金流特征准入实验。该实验仍不能修改生产模型或当前候选池。
