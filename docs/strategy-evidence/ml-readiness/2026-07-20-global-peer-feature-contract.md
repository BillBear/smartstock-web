# 详细资金流全局 Peer Set 特征契约修复

## 结论

**已修复未来研究资产的特征构造边界；当前两年冻结数据资产仍不可用于详细资金流训练。**

修复将 `flow_minus_industry_median` 拆为两个不能混淆的阶段：

1. symbol 分片内只计算历史时间序列资金流特征；
2. 汇总同一交易日全部 symbol 分片后，才按 `trade_date + industry_l1` 计算行业中位数。

该修复不修改 SmartStock 生产选股、排序、买卖、止盈止损、仓位、模型或页面。详细资金流组仍被
完整全市场 `95%` 覆盖门槛禁用。

## 发现的问题

旧实现从 `build_time_series_features` 调用详细资金流构造器。离线物化按 symbol 分片执行该阶段，
导致 `flow_minus_industry_median` 的 median 只基于同一 shard 的行业股票。分片布局因此会改变特征值，
这是错误的数据契约。

新增的跨 shard fixture 固定了反例：同一交易日完整 peer set 的值为
`[-0.1, -0.1, 0.1, 0.1]`，旧分片计算会退化为 `[0, 0, 0, 0]`。修复后整表与两个 symbol 分片的
结果逐行相同。

同时修正候选资产认证状态机：未提供任何 parity 日期时不能再由 `all([])` 被误标为通过，状态改为
`complete_feature_parity_not_run`。这防止“只检查覆盖、没有检查特征一致性”的认证被误解为候选通过。

## 真实冻结资产复认证

| 项目 | 结果 |
| --- | --- |
| 不可变源 run | `full-market-history-20260718-v2` |
| 源数据集 ID | `fm_2a6fcc93480110df4457` |
| 修复代码提交 | `d3f2341` |
| parity 日期 | `2025-02-14`, `2025-09-19`, `2026-04-17` |
| 使用未来行 | `0`（三个日期均为 0） |
| 特征 parity | 三个日期均失败，字段均为 `flow_minus_industry_median` |
| 原始详细资金流覆盖 | `94.92262455059985%`，低于 `95%` |
| 认证状态 | `complete_feature_contract_blocked` |
| `training_ready` / `production_integration_allowed` | `false` / `false` |

真实认证结果证明旧冻结训练数据保存的是与新全局 peer-set 契约不一致的值。它不能通过重写 parquet
或“补一列”修复；必须由原始、不可变分区重新物化新的特征资产，并重新执行字段覆盖、feature parity、
split、OOF 和样本外评估。旧资产仅保留为失败证据。

运行产物（不进入 Git）：

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/
  detailed-moneyflow-candidate-v3-global-peer-parity-20260720/
    candidate_asset_manifest.json
    field_coverage.csv
    parity_report.json
    progress.json
```

其中 manifest SHA256 为
`edb7241ae82658822064a86162bb9a728c4c661fd53bb68f7e5ebd8981c41496`，
parity report SHA256 为
`d6ddf6f5659333cc1ee01cfd30295d28b0c721cef7c28ba4456f710626e312a3`。

## 后续边界

本修复只消除了未来资产的 shard-layout 错误。新的详细资金流训练资产仍同时受两项阻断：

1. 当前 TuShare `moneyflow` 对北交所没有详细资金流覆盖，完整全市场覆盖为 94.9226%；
2. 当前冻结数据集的 peer-relative 字段已不符合新契约，必须重建而非复用。

在具备等价北交所来源或经单独批准的新研究 universe 之前，不得启用详细资金流特征进行全市场模型训练。

## 验证

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_full_market_ml_moneyflow_features \
  tests.test_detailed_moneyflow_candidate_asset \
  tests.test_certify_detailed_moneyflow_candidate_asset \
  tests.test_full_market_ml_features \
  tests.test_full_market_feature_materialization

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/certify_detailed_moneyflow_candidate_asset.py \
  --source-run-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-20260718-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/detailed-moneyflow-candidate-v3-global-peer-parity-20260720" \
  --code-commit d3f2341 \
  --parity-dates 2025-02-14,2025-09-19,2026-04-17
```

Observed focused test result: `Ran 34 tests ... OK`.
