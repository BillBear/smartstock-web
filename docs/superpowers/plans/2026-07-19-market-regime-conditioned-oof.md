# 市场状态条件化 OOF 研究计划

## 研究问题

上一轮在全市场上使用固定方向的简单评分卡，开发期 OOF 未通过门槛。这个结果不允许解释为“特征完全无效”：A 股的动量、成交和风险特征可能在不同市场环境下方向相反。本轮只检验以下可证伪假设：

> 使用信号日及以前可得的市场趋势和截面宽度划分状态后，固定的训练期特征方向是否能在同类市场状态的 OOF Top-K 中稳定优于 `adjusted_return_60d` 基线。

本轮是离线 `research_only`。不修改生产候选池、排序、评分、买卖、止盈止损、仓位、CoachService 或前端。

## 冻结研究契约

- 数据集：`fm2_c566fd1c47b64dde7f16`；使用其 V3 特征资产和既有开发期五折切分。
- 状态仅由当日及历史原始行情构造，绝不读取标签、未来收益、未来涨跌停或被污染的原时间留出集。
- `trend_up`：20 日市场指数收益大于 0，且当日有效股票上涨宽度大于等于 0.50。
- `trend_down`：20 日市场指数收益小于 0，且当日有效股票上涨宽度小于等于 0.50。
- `mixed`：其余历史完整交易日；不足 20 个历史交易日为 `insufficient_history`，不参与本轮比较。
- 20 日市场波动率、涨跌停宽度和均线宽度只作诊断字段，不作为本轮状态门槛。
- 每个外层折中，每个状态只能用该折训练日期与训练股票拟合方向；验证日期和验证股票不得参与方向、阈值或特征组选择。
- 方向证据需至少 20 个训练日 IC；否则该特征组在该折/状态为 inactive，不能以常数分数参与比较。
- 每个状态/折至少 5 个验证日才产出指标；五个外层折存在日期重叠，所有结果只允许折内解读，禁止合并为独立样本量。

## 实施任务

1. 新增点时市场状态构造器与单元测试。
   - 输出逐日状态、20 日收益、20 日波动、上涨宽度、均线宽度、涨跌停宽度和历史完整标记。
   - 测试未来行情不影响既有日期、同日冲突指数收盘价被拒绝、宽度只使用有效行情。
2. 新增状态条件化训练期评分卡 OOF 执行器。
   - 固定比较：60 日复权动量、反向动量诊断、H1/H2/H3 和组合评分卡。
   - 输出逐折/逐状态方向、预测、排序、bootstrap、组合 Top-K 交易模拟和候选门槛。
3. 新增 CLI、可运行产物和证据报告。
   - 每一阶段写入 `progress.json`；产物落在外部 `ml-assets`，不提交 Git。
   - 只有 A 象限同状态、至少 4 个可评估折同时满足 Precision@5、NDCG@10、Top5 平均收益、最大回撤以及 bootstrap 下界要求，才可标记开发期候选；任何结果仍不得接入生产。

## 验收和拒绝标准

- `git diff --check` 必须通过。
- 新增单元测试必须先红后绿；既有训练期评分卡和 V3 证据测试不得回归。
- 运行产物必须记录数据集、特征契约、切分和代码哈希，以及每个无效状态/特征组的原因。
- 若任一候选不满足上述所有 A 象限门槛，报告必须标为 `research_only_failed_gate`，不得以局部状态收益替代总体证据。
- 实验完成后运行后端测试；如环境或既有测试存在独立失败，必须原样记录，不得以此声明研究通过。

## 复现命令

```bash
git diff --check
cd backend && /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -p 'test_market_regime.py' -v
cd backend && /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python -m unittest discover -s tests -p 'test_regime_scorecard*.py' -v
cd backend && /Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python scripts/run_regime_scorecard_oof.py --output-dir /Users/xiong/Documents/SmartStock/ml-assets/runs/fm2_c566fd1c47b64dde-regime-scorecard-oof-20260719
```
