# 2026-07-19 Alpha 目标评分卡 OOF 证据

## 结论

本轮没有通过开发期候选门槛，状态为 `research_only_failed_gate`，不允许接入生产。

将训练期方向目标从绝对净收益切换为连续 `alpha_target_10d`，确实使 H1 动量趋势在前两折获得了稳定训练方向，也使组合评分卡在前两折相对“净收益方向评分卡”有所改善。但它没有在任一特征组中满足相对 60 日动量基线的联合 A 象限门槛：组合与 H2 均为 `0/5`，H1 仅 2 折有方向且不能通过 Precision@5、NDCG@10、Top5 收益、回撤和 bootstrap 下界的联合检查。

因此，标签混合是应当保留的工程诊断，但“只把方向目标换成 Alpha”不是当前模型区分度不足的充分解决方案。不能据此接入风险模型、增加复杂度或改变生产策略。

## 冻结对照

- 代码提交：`5404bbef274251a0c93521d257500567b1eecd31`
- 数据集：`fm2_c566fd1c47b64dde7f16`
- V3 特征契约 SHA256：`4285a84755f8c27a983cf4bec8b36bdf4b83bf291c3f2ddb0ec71f9d5546490f`
- 开发期：327 个交易日、1,770,788 个固定比较行、五个重叠外层折；所有指标折内计算，不合并为独立样本。
- 训练期唯一变化：特征方向的 Spearman IC 从 `net_return_after_cost_10d` 改为 `alpha_target_10d`。
- 不变项：H1/H2/H3 特征组、60 日动量基线、反向诊断、A/C 股票切分、旧强势 Precision@K/NDCG@K、Top-K 收益、成本、滑点、交易路径、bootstrap 和候选门槛。
- 正式运行：1000 次 circular-block bootstrap。
- 运行目录：`/Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-alpha-target-scorecard-oof-20260719`

## 方向结果

- H1：仅第 1、2 折存在方向（`adjusted_return_60d=-1`）；第 3–5 折 inactive。
- H2：五折均有效，但始终由负向 `amount_log` 和/或 `volume_cv_20d` 主导。
- H3：五折均 inactive。
- 组合：五折可评分，但实际主要由 H2 和前两折 H1 构成。

这说明 Alpha 目标没有释放出稳定的行业相对强度方向，也没有消除流动性特征方向的状态依赖。

## A 象限结果

| 折 | 60 日动量 P@5 | Alpha 组合 P@5 | 60 日动量 NDCG@10 | Alpha 组合 NDCG@10 | Alpha 组合 P@5 uplift 95% 下界 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 13.5% | 11.5% | 0.1074 | 0.1018 | -8.0pp |
| 2 | 14.0% | 7.5% | 0.1219 | 0.1006 | -20.5pp |
| 3 | 16.5% | 1.5% | 0.1423 | 0.0749 | -25.0pp |
| 4 | 7.0% | 0.5% | 0.0612 | 0.0711 | -11.0pp |
| 5 | 4.0% | 1.5% | 0.0643 | 0.0453 | -5.0pp |

Alpha 组合在第 1、2 折相对净收益方向组合有所改善，例如第 1 折 P@5 从 6.0% 到 11.5%，第 2 折从 2.0% 到 7.5%。但这仍低于固定 60 日动量基线，并且所有五折 bootstrap 下界均小于零。组合候选因此 A 象限通过数为 `0/5`，C 象限仅 `4/5` 未出现 NDCG 崩塌。

H1 的局部路径更有信息，但仍不达标：第 1 折 P@5 为 13.0%、NDCG@10 为 0.1244、Top5 平均收益 3.37%，却 bootstrap 下界为 -10.5pp；第 2 折也同时低于基线。不能把收益或回撤的局部改善选择性解释成排序能力。

## 研究决定

1. 保留“排序目标”和“风险目标”应分离的标签诊断结论。
2. 拒绝把 Alpha 目标评分卡或任何局部 H1 结果接入生产，也不进入风险模型叠加阶段。
3. 下一项研究不再改变标签或模型，而是先补齐并审计缺失的点时市场/行业横截面特征组：市场宽度、行业扩散度、行业相对成交活跃度、大小盘风格和涨跌停宽度。每个特征必须先通过覆盖率、未来泄漏、按日 IC、分桶收益和状态稳定性审计，才允许进入下一次同口径 OOF 对照。

## 复现

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/task-15-alpha-target-oof/backend
/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_alpha_target_scorecard_oof.py \
  --source-dataset-root /Users/xiong/Documents/SmartStock/ml-assets/datasets/fm2_c566fd1c47b64dde7f16 \
  --feature-asset-root /Users/xiong/Documents/SmartStock/ml-assets/feature-assets/fmf2_c566fd1c47b64dde-4285a84755f8-contract-v3 \
  --output-root /Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-alpha-target-scorecard-oof-20260719 \
  --code-commit 5404bbef274251a0c93521d257500567b1eecd31 \
  --bootstrap-iterations 1000
```
