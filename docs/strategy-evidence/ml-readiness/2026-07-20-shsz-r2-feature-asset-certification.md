# SH/SZ R2 特征资产认证

## 结论

`shsz_r1_feature_asset_v1` 的 **v2** 派生资产已通过数据读取、特征覆盖、泄漏和
offline/online parity 认证。它只允许进入后续的开发期特征有效性审计，不能训练生产候选，
更不能改变 SmartStock 的选股、排序、买卖、止盈止损、仓位或页面推荐。

| 项目 | 结果 |
| --- | --- |
| 资产状态 | `complete` |
| `research_ready` / `production_integration_allowed` | `true` / `false` |
| 行数 | 2,546,333 |
| 股票数 | 5,280 个 `.SH` / `.SZ` 代码 |
| 特征日期 | 496 个，`2024-06-03` 至 `2026-06-18` |
| 特征数 | 111 |
| 重复 `(trade_date, symbol)` | 0 |
| `.BJ` 行 | 0 |
| 五折最低特征覆盖率 | 95.6954%，门槛 95% |
| 三个固定日 parity | 全部通过，容差 `1e-8` |
| 最终未来时间 holdout | `awaiting_model_freeze_and_future_labels` |

本资产仍不含标签、未来收益、下一交易日执行字段或任何模型预测；它不能被解释为模型准确率、
收益率或交易准入证据。

## 不可变输入与绑定

| 输入 | 路径 / SHA256 |
| --- | --- |
| SH/SZ 原始面板 | `$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-shsz-20260720-v2` |
| 面板 manifest | `19db3e63672bd32c39837bed8d2db6221cf21a8b5ec02b8608dbe07c7ee17ea9` |
| R1 开发标签与 split | `$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-development-labels-v1-20260720` |
| 标签 registry | `6dc4602b6f11fb88a06aeabd1d47ee16409a05a9b3f6463be502c3ac65ee48cd` |
| 标签 split | `46df4aa5808bd39ea92952337a2fbbc00722acab1482e6ed69ca380655321664` |
| 特征代码提交 | `4dd10ac` |
| 特征资产 manifest | `75bc1842faad1ec979f470afdb32fb13e3de79f64cd0261e9459658c779f5146` |

最终资产目录位于 Git 外，约 `4.2G`：

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/
  shsz-r1-v2-feature-asset-v2-20260720/
    matrix/trade_date=YYYY-MM-DD/data.parquet
    data_quality_report.json
    feature_coverage_report.json
    materialization_contract.json
    feature_asset_manifest.json
```

`feature_asset_manifest.json` 列出的 496 个矩阵分区均已重新计算 SHA256，结果为
`hash_mismatch_count = 0`。

## 质量门禁

1. **样本边界**：仅接受 `shsz_a_share_v1` 的 `.SH` / `.SZ`，不复用旧全市场 feature
   值作为输入；北交所行数为零。
2. **输入时间边界**：开发特征仅使用不晚于 `2026-06-18` 的原始面板字段。资产 schema 中不含
   `future_`、`label_`、`next_`、`entry_`、`exit_`、`tp_`、`sl_`、`gross_return`、
   `net_return`、`mfe` 或 `mae` 字段。
3. **资金流门禁**：详细资金流字段最低日覆盖率为 99.9803%，高于固定 95% 准入线；资金流特征
   没有因缺失而填造。
4. **全局 peer set**：跨截面排名、行业相对收益和
   `flow_minus_industry_median` 均在完整同日 SH/SZ 截面计算，未在单个 symbol shard 内近似。
5. **五折覆盖**：5 个 sealed walk-forward 验证折的 455 个“特征-折”覆盖值全部不低于 95%。
6. **同源性**：在 `2025-02-14`、`2025-09-19`、`2026-04-17` 三日各抽取 128 个稳定选择的
   股票，离线矩阵与 `OnlineFeatureProvider` 所得全部注册特征在 `1e-8` 容差内一致；三次检查
   的 `future_rows_used = 0`。

## v1 资产处置

最初的 `shsz-r1-v2-feature-asset-v1-20260720` 完成了特征值计算，但文件内
`trade_date` 为 Arrow `large_string`，而 `trade_date=...` Hive 分区推断为 Arrow `string`。
标准 `pyarrow.dataset(..., partitioning="hive")` 因类型冲突无法读取。

该资产没有删除或覆盖，保留作失败证据；不得作为后续训练输入。提交 `4dd10ac` 将 `trade_date`
和 `symbol` 显式写为 Arrow `string`，并新增 Hive 扫描回归测试。v2 使用相同输入、标签边界、
特征契约和 parity 日期重新物化，标准 Hive 扫描已通过。

## 复现与验证

```bash
cd smartstock-web/backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_shsz_feature_asset \
  tests.test_full_market_ml_moneyflow_features \
  tests.test_full_market_ml_features \
  tests.test_full_market_ml_feature_contract

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/materialize_shsz_r2_feature_asset.py \
  --panel-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-shsz-20260720-v2" \
  --label-root "$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-development-labels-v1-20260720" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/shsz-r1-v2-feature-asset-v2-20260720" \
  --code-commit 4dd10ac \
  --parity-dates 2025-02-14,2025-09-19,2026-04-17 \
  --materialized-shard-count 16
```

观测结果：定向测试 `29` 项通过；完整后端测试 `673` 项通过。完整套件仍会输出既有 SQLite
`ResourceWarning` 和旧候选快照 preflight 的 `blocked` 状态，它们不改变本 R2 资产的认证结论。

## 下一步与禁止事项

下一任务只允许在 R1 sealed development folds 上做特征有效性审计：逐特征日截面 IC、分桶
alpha、稳定性、相关性和按市场状态/行业/流动性分层表现。只有先完成该审计，才可以提出一条
可证伪的开发期模型假设。

禁止使用 R2 资产直接训练并声称结果有效；禁止打开正式未来 holdout；禁止以此资产替换当前
`paper_only` 弱模型或改变 CoachService 决策。
