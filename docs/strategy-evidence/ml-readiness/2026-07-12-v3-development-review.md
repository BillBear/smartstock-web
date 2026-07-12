# SmartStock AI Full-Market ML V3 Development Review

## 1. 结论

本轮全市场监督学习训练已完整执行到开发期 OOF 结束，但没有通过研究门槛，模型状态为 `research_only_failed_gate`。

结论不是“TuShare 数据不可用”或“16G Mac 无法训练”，而是：当前 73 个通过审计的特征，在严格的下一交易日开盘执行口径、交易成本/滑点和外层时间 OOF 下，没有形成稳定的 Top-K 区分能力。当前模型不允许接入生产，也不允许改变智能选股结果。

本轮没有打开最终时间留出集。历史 final split 仍属于已作废的开发材料，只用于检查边界，不作为模型调优或生产证据。

## 2. 执行范围

### 已完成阶段

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| 全市场面板重建 | complete | 2,764,158 行、511 个交易日、64 个 parquet 分片 |
| 数据质量审计 | complete | 无重复键、无阻断项；板块覆盖 MAIN/CHINEXT/STAR |
| 规范化标签 | complete | 下一交易日开盘入场，10 日持有，成本 0.03%、滑点 0.1% |
| 特征审计 | complete | 89 个特征完成覆盖、IC、分桶、漂移和相关性审计；73 个允许进入候选模型 |
| 开发期嵌套 OOF | complete | 350 个外层 OOF 交易日；每个外层折只使用更早内层时间折选择参数 |
| 未见股票验证 | complete | C 象限 1,037 只开发期未见股票，350 个交易日 |
| 特征组消融 | complete | momentum、amount_turnover、technical、risk、market_industry、moneyflow |
| 分类器和概率校准 | complete | strong/severe 各 5 折；校准只使用先前外层折拟合 |
| 正式最终拟合 | blocked | 开发门槛失败，按协议禁止启动 |
| 未来时间留出 | not opened | 未积累模型冻结后的 40 个可标注交易日 |

### 运行资产

以下路径是本地研究资产，不提交 Git：

- `runtime/ml_full_market/v3-rebuild/artifacts/full-build/dataset-v3/`
- `runtime/ml_full_market/v3-rebuild/artifacts/full-build/dataset_registry_v3.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/full-build/quality_report_v3.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/full-build/label_report_v3.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/full-build/split_plan_v3.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/feature-audit/report_v3.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/dev-train-v3/oof_predictions.parquet`
- `runtime/ml_full_market/v3-rebuild/artifacts/dev-train-v3/development_report.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/dev-train-v3/candidate_manifest.json`
- `runtime/ml_full_market/v3-rebuild/artifacts/dev-train-v3/checkpoints/`

数据注册清单记录了 122 个文件、约 15.7 GB 和每个文件的 SHA256。数据、OOF 和 checkpoint 可复用；模型没有接入生产。

## 3. 数据和标签验收

### 数据质量

- 全面板：2,764,158 行。
- 10 日可标注样本：2,404,837 行，482 个可标注交易日。
- 开发期外层 OOF：350 个交易日。
- 每日有效股票覆盖满足质量阈值；质量报告 `blocking_codes` 为空。
- `duplicate_key_count = 0`。
- 涨停、跌停、停牌、次日不可交易字段均参与标签和可交易性判断。
- 资金流覆盖约 94.2%，但质量层将资金流组标记为可选/需单独 OOF 证明，不能把它当作无条件可靠特征。

### 标签分布

在 2,404,837 条可标注样本中：

- `label_strong_path_10d`：197,208 条，8.20%。
- `label_severe_negative_10d`：936,165 条，38.93%。
- `relevance_grade_10d`：0/1/2/3/4 比例约为 60.14%/23.56%/8.10%/4.16%/4.04%。
- 路径存在 3,867 条歧义记录；这些记录被保留在质量报告中，不能悄悄当作确定的止盈/止损结果。

标签工程没有发现“未来价格进入信号日特征”的直接证据，但样本的正负路径不对称，后续研究必须继续检查强势标签和严重负面标签是否被混合成过于宽泛的排序目标。

## 4. 特征审计结果

本轮审计了 89 个候选特征，目标分别为 `net_return_after_cost` 和 `label_severe_negative_10d`，没有使用资讯分作为主特征。73 个特征通过覆盖/审计准入。

几个单变量结果较好，但不能直接等价为模型有区分能力：

- 对严重负面标签，波动率/ATR 类特征的截面 IC 较高且方向较稳定。
- 对成本后收益，`adjusted_close_to_high` 的平均 IC 约 0.031，资金流相关特征约 0.025 至 0.026。
- `amount_log`、`adjusted_return_60d` 等特征存在明显方向关系，但单变量 IC 不能证明组合后的 Top-K 排序优于 baseline。
- 漂移最大的特征包括 `market_index_volatility_20d`、`listing_age_log` 和部分估值/市场状态特征，说明跨市场阶段稳定性不足。
- 资金流不是本轮失败的唯一原因：在当前审计和模型中，它没有被证明能带来独立、稳定的 OOF 增益。

## 5. OOF 结果

### A：开发期时间 OOF

| 指标 | V3 模型 | 成交额 baseline | 随机 baseline |
| --- | ---: | ---: | ---: |
| Precision@3 | 10.76% | 16.86% | 8.86% |
| Precision@5 | 9.66% | 16.00% | 8.74% |
| Precision@10 | 8.94% | 14.46% | 8.17% |
| NDCG@10 | 0.1031 | 0.1402 | 0.0923 |
| Top5 平均成本后收益 | 1.12% | 1.25% | 1.60% |
| Top5 中位数成本后收益 | -0.06% | 0.34% | 0.32% |
| Top5 正收益比例 | 49.54% | 48.11% | 53.26% |
| 严重负面比例 | 42.11% | 52.80% | 36.74% |

V3 模型略高于随机的部分指标，但明显低于成交额 baseline；尤其 Top5 中位数收益为负，不能作为高精度推荐模型。

### C：开发期未见股票

| 指标 | C 象限 |
| --- | ---: |
| Precision@5 | 11.03% |
| NDCG@10 | 0.1200 |
| Top5 平均成本后收益 | 1.97% |
| Top5 中位数成本后收益 | -0.08% |
| Top5 正收益比例 | 49.66% |

C 象限没有出现完全崩塌，说明问题不是简单的“模型只记住了训练股票”；但 C 仍没有满足高精度门槛，且 Top5 中位数仍为负。

### 风险扣分和选择稳定性

风险扣分系数 `0.2` 是预注册值，不由外层 OOF 选择。诊断试验显示：

- alpha=0.0：NDCG@10 约 0.1025，Precision@5 约 9.49%。
- alpha=0.1：NDCG@10 约 0.1042，Precision@5 约 10.40%。
- alpha=0.2：NDCG@10 约 0.1031，Precision@5 约 9.66%。
- alpha=0.3：NDCG@10 约 0.1036，Precision@5 约 9.14%。

这只能说明风险扣分存在敏感性，不能据此重新挑选最优 alpha；在下一轮研究中应把风险模型作为单独假设验证。

外层折选择的 ranker 参数不一致：第 1/3 折选择 `15/4/200`，第 2 折选择 `31/6/200`，第 4 折选择 `31/6/500`，第 5 折选择 `15/4/500`。这说明参数选择对市场阶段敏感，不适合直接冻结为生产模型。

## 6. 根因判断

### 已排除的根因

1. 不是只用了十几只股票：本轮使用全市场面板，开发期每天约 5,000 只有效样本。
2. 不是 Python 3.13 或 LightGBM 没有安装：环境已通过预检，训练和分类器均真实执行。
3. 不是训练没有完成：外层排序、C 象限、消融、分类器和 OOF 均已完成并落盘。
4. 不是未见股票完全失效：C 象限指标略高于 A，但仍未过门槛。

### 当前最可能的核心原因

1. **标签目标与可排序目标不完全一致。** `relevance_grade_10d` 同时混合收益分位、路径约束和风险事件，正样本稀疏、严重负面比例高；模型学到“风险/波动”并不等于能把未来强势股票排到 Top-K。
2. **单变量 IC 与多变量 Top-K 结果脱节。** 个别特征的 IC/ICIR 看起来不错，但组合后没有战胜成交额 baseline，说明存在冗余、方向冲突、非线性阈值或状态条件效应。
3. **市场状态漂移明显。** 市场波动、上市年龄、估值等特征跨阶段分布漂移，单一全期模型难以稳定表达风格切换。
4. **强势样本不是单一形态。** 突破、回调修复、行业领涨和资金驱动可能对应不同特征组合；把它们压成一个排序目标会稀释区分边界。
5. **当前 baseline 本身很强。** 成交额 baseline 的 Precision@5 和 NDCG@10 高于 V3，后续模型必须证明增量价值，而不是只证明略高于随机。

## 7. 门禁结论

- 开发期门禁：**failed**。
- final fit：**禁止启动**。
- 历史 final holdout：**禁止读取标签用于调优或准入**。
- 未来正式 holdout：**尚未开放**，需模型冻结后重新收集至少 40 个可标注交易日。
- 生产接入：**禁止**。
- 当前生产策略和页面：**未修改**。

## 8. 下一轮只允许选择一个研究假设

下一轮不应继续无目的增加特征或模型。建议按以下顺序单独验证，每轮只改一个研究变量，并保留同一数据切分和成本口径：

1. **标签拆分实验：** 分别训练“未来收益 Top-K”和“路径可交易”两个排序目标，验证混合标签是否导致目标冲突。
2. **状态条件实验：** 只增加市场状态/行业状态交互，不改变基础特征，检查波动率和动量在不同状态是否反向。
3. **简单评分卡对照：** 用固定方向、分位化和逻辑回归与 LightGBM 对比，验证复杂模型是否真的提供增益。
4. **资金流独立增益实验：** 在通过覆盖门槛的日期上做严格 OOF 增量检验；没有增益就从主模型剔除。

每个实验必须以成交额 baseline 为主对照，至少报告 Precision@3/5/10、NDCG@10、Top5 成本后收益、中位数收益、最大回撤、C 象限和市场状态分层。任何实验未通过，记录负结论，不打开未来留出集。

## 9. 复现命令

本轮使用 Homebrew Python 3.13 虚拟环境：

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python -m unittest tests.test_full_market_ml_trainer
.venv-ml-py313/bin/python -m compileall -q app scripts
git diff --check
```

研究资产复核：

```bash
cd smartstock-web/backend
.venv-ml-py313/bin/python - <<'PY'
import json
from pathlib import Path
p = Path('../runtime/ml_full_market/v3-rebuild/artifacts/dev-train-v3/development_report.json')
d = json.loads(p.read_text())
print(d['preliminary_status'])
print(d['failed_gates'])
print(d['oof_metrics'])
PY
```

本轮实际完成的 focused verification：

```text
4 trainer checkpoint/calibration tests: OK
compileall -q app scripts: OK
git diff --check: OK
```

完整 trainer 套件在当前实现上实际结果为 `26 tests in 57.897s, OK`；完整后端套件在补齐 Python 3.13 兼容运行时依赖后实际结果为 `344 tests in 68.657s, OK`。测试过程中有既有 SQLite `ResourceWarning`，没有失败测试。

仓库原始 `requirements.txt` 的 `pydantic==2.5.3` 在 Python 3.13 上触发源码构建失败，因此本轮验证环境使用了 Python 3.13 兼容的新版 Pydantic/FastAPI/SQLAlchemy，并补装了现有依赖 `akshare`。这暴露出后续应单独治理 Python 3.13 的依赖锁定，但不属于本轮策略或训练逻辑变更。

## 10. 最终判断

本轮训练工程已从“不可观测、不可恢复、验证口径可能泄漏”修到可以保存、复用和审查；但模型效果没有达到目标，不能宣称训练成功，也不能合并为生产策略。下一步应先做单一标签拆分实验，而不是扩大模型规模或把当前模型接入 CoachService。
