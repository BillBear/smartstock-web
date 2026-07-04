# 2026-07-04 ML Training Dataset Readiness Audit

## 结论

当前本地数据库已经有全 A 级别的最新市场快照，但历史快照日期数量仍不足以支撑全市场 ML 训练数据构建。因此，不能训练新生产模型，也不能把当前 ML 概率展示为可靠胜率。

- 状态：`blocked`
- dataset_build_ready：`false`
- production_ml_ready：`false`
- 最新全市场快照日期：`2026-07-03`
- 最新全市场快照数量：`5210`
- 满足全市场阈值的快照日期：`18`
- 估算样本数：`31260`
- 阻塞原因：`snapshot_date_count_below_required`、`estimated_sample_count_below_required`

## 复现命令

```bash
cd /Users/xiong/Documents/SmartStock/smartstock-web/backend
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/audit_ml_training_readiness.py \
  --train-start 2024-07-01 \
  --train-end 2026-07-03 \
  --sample-step 3 \
  --min-full-market-count 5000 \
  --min-symbol-count 1500 \
  --min-time-span-days 730 \
  --min-estimated-samples 100000 \
  --min-snapshot-dates 30 \
  --output-json /tmp/smartstock-ml-training-readiness-20260704.json \
  --output-md /tmp/smartstock-ml-training-readiness-20260704.md
```

关键输出：

```text
status: blocked
dataset_build_ready: False
production_ml_ready: False
latest_snapshot_trade_date: 2026-07-03
latest_snapshot_count: 5210
eligible_full_market_snapshot_date_count: 18
estimated_sample_count: 31260
blocking_codes: snapshot_date_count_below_required,estimated_sample_count_below_required
```

## 观察值

```text
train_start: 2024-07-01
train_end: 2026-07-03
time_span_days: 732
snapshot_date_count: 18
eligible_full_market_snapshot_date_count: 18
symbol_count: 5210
board_count: 3
industry_count: 111
sample_step: 3
estimated_sample_count: 31260
```

## 判断

这次审计说明“最新全市场样本”已经可用，但“全市场历史样本”还不够：

- 训练跨度达到 732 天，满足 24 个月下限。
- 最新快照 5210 只，满足全 A 覆盖要求。
- 板块覆盖和行业覆盖满足基础要求。
- 但只有 18 个全市场快照日期，低于 30 个最低审计阈值。
- 按 `sample_step=3` 估算只有 31,260 条样本，低于 100,000 条训练样本最低要求。

## 影响

本审计只读数据库，不训练模型、不替换模型 artifact、不修改生产选股、排序、买入、卖出、止盈、止损或仓位逻辑。

下一步应先补齐全市场历史快照覆盖，再构建全市场训练数据集。新模型必须完成 final time holdout、stock holdout、walk-forward 和分桶命中率样本外验证后，才能进入候选准入评审。
