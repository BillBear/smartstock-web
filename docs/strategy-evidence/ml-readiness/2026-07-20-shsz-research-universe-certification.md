# SH/SZ 两年研究 Universe 认证

## 结论

`shsz_a_share_v1` 已通过原始分区的只读研究 universe 认证，可作为**下一步新资产重建**的
输入边界；它不是模型训练、shadow 或生产接入授权。

本认证只改变离线研究样本边界：保留 `.SH` / `.SZ`，排除 `.BJ`。SmartStock 的生产候选池、
排序、买卖、止盈止损、仓位和页面均未修改。

## 不可变来源与结果

| 项目 | 结果 |
| --- | --- |
| 原始来源 run | `full-market-history-20260718-v2` |
| 认证代码提交 | `47e69f8` |
| 交易日 | 516 |
| 研究 universe 唯一股票数 | 5,284 |
| 排除的北交所唯一代码数 | 329 |
| 日线 / 历史 SH/SZ 活跃 universe 覆盖最小值 | 98.9515% |
| 日线 / 历史 SH/SZ 活跃 universe 覆盖中位数 | 99.7504% |
| 详细资金流覆盖最小值 | 99.9803% |
| 详细资金流覆盖中位数 | 100.0000% |
| 状态 | `complete_research_universe_certified` |
| `research_ready` / `production_integration_allowed` | `true` / `false` |

认证输出位于 Git 外的不可变派生目录：

```text
$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/
  shsz-universe-contract-v2-20260720/
    universe_contract.json
    daily_coverage.csv
    progress.json
```

`universe_contract.json` SHA256：
`18724915de7521dd0e5943f57396417b02346323e7f0c75cebcfdc6aa5e4a8ec`。

## 主数据异常的处理

`300114.SZ` 在 170 个历史日线、复权、估值和涨跌停分区中可观察到，但不在来源 run 的
`stock_basic` L/D/P 快照中；使用当前 TuShare 凭据复查 L/D/P 也未返回该代码。

它没有可复现的上市年龄、历史状态和 ST 输入，因此不能进入训练 universe。认证器将其列为
`unresolved_daily_master_symbols` 并在每个受影响日期从训练分母、日线观察值和资金流覆盖分子
中同时排除。它不是被填零、被补造主数据或被静默包含。这个排除仅影响一只缺主数据的研究行，
并保存在 manifest 中供后续复查。

## 后续门禁

R0 仅解决“SH/SZ 原始数据能否定义完整研究 universe”。下一步 R1 必须从原始分区建立新的
`full-market-history-shsz-*` run，重新生成面板、标签、split 和 dataset ID；不得过滤或复用旧
冻结 dataset 的特征列。新的特征资产必须使用全局 `trade_date + industry_l1` peer set，随后重新
通过 sample/label/split 和 offline/online parity，才能进行 H1/H2/H3 特征证据。

## 验证

```bash
cd backend
PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest \
  tests.test_shsz_research_universe \
  tests.test_certify_shsz_research_universe \
  tests.test_moneyflow_coverage_forensics

PYTHONPATH=. /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python \
  scripts/certify_shsz_research_universe.py \
  --source-run-root "$SMARTSTOCK_ML_ASSET_ROOT/runs/full-market-history-20260718-v2" \
  --output-dir "$SMARTSTOCK_ML_ASSET_ROOT/derivations/fm_2a6fcc93480110df4457/shsz-universe-contract-v2-20260720" \
  --code-commit 47e69f8
```

Observed focused result: `Ran 9 tests ... OK`.
