# 2026-07-19 全市场标签语义审计

## 结论

审计完成，数据资产中的旧标签没有被错误写入：按原标签定义在 327 个注册开发期日期、1,691,878 个可标注样本上重建后，`label_strong_path_10d` 和 `label_severe_negative_10d` 的逐行差异为 `0`。

但三种标签表达的是不同目标，不能相互替代，也不应无区分地混入一个二元训练目标：

- 旧强势标签：未来 10 日净收益截面 Top10%，最大浮盈至少 6%，最大回撤优于 -8%，且无底部收益/止损/跌停等严重事件。它是严格的“收益加路径”结果标签。
- Alpha Top10：未来市场和行业相对收益 Top10%，是纯截面排序结果，不保证路径可交易。
- 绝对可交易：净收益至少 3%、最大回撤优于 -6%、无先止损、无路径歧义和未来跌停，是广义绝对收益事件，不是稀缺的 Top-K 排序标签。

因此，当前训练效果弱不能归因于标签损坏；更可能的机制问题是用一个严格的“排序 + 路径风险”合成二元标签，要求单一排序器同时预测两种不同且部分不可由收盘特征区分的未来事件。

本审计为 `research_only`。没有修改生产标签、特征、模型、选股、排序、买卖或风控。

## 输入和完整性

- 代码提交：`f9cf37a0b66c8c354e80f680a37201f4c0631fec`
- 数据集：`fm2_c566fd1c47b64dde7f16`
- 数据集 SHA256：`e07b629d78c5ed04a8904dff08d18340cf90bbb395dd89a5b7cb2cc8340f4693`
- V3 特征契约 SHA256：`4285a84755f8c27a983cf4bec8b36bdf4b83bf291c3f2ddb0ec71f9d5546490f`
- 开发期：327 个注册日期、5,398 只股票、1,691,878 条 `eligible_for_training_10d` 样本。
- 封存时间留出未被读取；加载器只遍历 `development_dates` 分区。
- 运行目录：`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-label-semantic-audit-20260719`

## 事件率和一致性

| 结果视图 | 数量 | 占可标注样本 | 含义 |
| --- | ---: | ---: | --- |
| 旧强势 `label_strong_path_10d` | 140,646 | 8.313% | 严格收益加路径 |
| Alpha Top10 `alpha_top10_10d` | 169,041 | 9.991% | 相对收益排序 |
| 绝对可交易 | 485,876 | 28.718% | 宽松的绝对收益/路径事件 |
| 旧严重风险 | 610,377 | 36.077% | 旧路径风险定义 |
| Alpha/绝对严重风险 | 608,861 | 35.987% | 两者逐行一致 |

重叠矩阵：

- 旧强势与 Alpha Top10：交集 131,533，旧强势独有 9,113，Alpha 独有 37,508，Jaccard `0.7383`。
- 旧强势与绝对可交易：交集 138,199，绝对可交易独有 347,677，Jaccard `0.2830`。
- 旧严重风险与 Alpha/绝对严重风险：Jaccard `0.9488`；后两者完全一致。
- 绝对可交易与绝对严重风险交集为 `0`，固定决策标签契约没有逻辑重叠。

## 关键诊断

`Alpha Top10` 但不是旧强势的 37,508 个样本中：

- 28,302 个（75.46%）被旧严重风险覆盖。
- 其中 56.86% 先止损，36.34% 最大回撤达到或低于 -8%，18.39% 出现未来跌停。
- 8,550 个没有进入旧净收益 Top10。
- 656 个仅因最大浮盈未达到 6% 被排除。

平均净收益也验证三者的角色不同：全样本为 `0.817%`，Alpha Top10 为 `19.076%`，旧强势为 `19.675%`，绝对可交易为 `10.226%`。因此：

1. Alpha Top10 本身不是可交易建议，因为高相对收益样本中包含大量严重路径风险。
2. 旧强势不是纯排序标签，它在少数正样本中混入了收益排名、波动路径和交易可达性。
3. 绝对可交易的正样本过宽，不能作为 Top5/Top10 精度模型的唯一主目标。

## 下一轮唯一研究假设

下一轮不调阈值、不增加特征、不增加模型复杂度。只比较一个改变：

> 用连续的 `alpha_target_10d` 或市场/行业超额收益学习排序方向，用独立的严重风险标签做后验风险扣分；仍以旧强势、Top-K 收益、回撤、成本和滑点评估最终候选。

这会直接检验“目标解耦”是否比当前的严格二元标签更有区分力。训练期方向只能使用该折训练行的 Alpha 目标；评估仍只报告同折的旧强势 Precision@K、NDCG@K、Top-K 收益、最大回撤和 C 象限结果。未通过既有五折 A/C 门槛，仍保持 `research_only_failed_gate`。

## 复现

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-14-label-semantic-audit/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_label_semantic_audit.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-label-semantic-audit-20260719 \
  --code-commit f9cf37a0b66c8c354e80f680a37201f4c0631fec
```
