# 2026-07-06 Funnel Recall Ablation Evidence

## 结论

本轮先复查原方案，发现原离线召回实验有一个关键遗漏：它只比较 `220 / 300 / 500 / multi_channel` 这些粗粒度召回池大小，没有单独隔离“行业 cap”对 `全 A -> 预筛 -> 召回池` 的影响。因此它不能回答当前页面里 `5203 -> 4033 -> 240` 到底是被 TopN 压缩，还是被行业分散上限过早剔除。

本轮已补上行业 cap 消融实验和漏斗损耗统计，但没有修改生产选股、排序、买入、卖出、止盈止损或仓位逻辑。

当前真实数据结论：

- 行业 cap 确实造成大量漏斗损耗：`production_cap_240` 在 9 个可用快照日累计 `industry_cap_rejected_count=23658`。
- 仅去掉行业 cap 不能证明策略更好：`no_industry_cap_240` 的 Precision@3/5 与 `production_cap_240` 相同，NDCG@10 反而略低。
- 仅扩大召回池也不能解决排序：`recall_220_deep_150 -> recall_500_deep_500` 的 Precision@3/5 没有改善，NDCG@10 随候选池扩大下降。
- 多通道召回有信号：`multi_channel_union` 的 Top5 平均收益最高，但 Precision@5 和 NDCG@10 仍未通过门禁。
- 本轮证据状态仍是 `blocked`，`production_switch_ready=false`，原因是没有实验组通过生产门禁，且覆盖日期仍不足 30 个。

因此，当前不能把“去掉行业 cap”“展示更多票”或“多通道 union”直接切入生产策略。正确下一步是继续用真实快照补齐覆盖日期，并把漏斗规则改造方向限定为可验证实验：先证明召回能覆盖未来强势股，再证明排序能把它们排到前面。

## 方案自检

### 原方案遗漏

原方案的问题不是方向错，而是消融层次不够细：

1. 没有把 `4033 -> 240` 拆成 `行业 cap 损耗` 和 `TopN 损耗`。
2. 没有在报告中输出每天的 `input / prefilter / recall / deep_analysis / cap rejected / topn rejected`。
3. 没有证明 `220 / 300 / 500` 的比较是否被 `max_rows_per_day` 截断影响。
4. 没有把“生产式行业 cap 召回”和“无行业 cap 召回”放在同一评价矩阵里。

这些遗漏会导致错误决策：如果只看最终收益，可能误以为“扩大候选池”就是答案；如果只看漏选数量，又可能误以为“去掉 cap”一定提升排序。两种结论都不够严谨。

### 本轮优化

本轮新增三个只读离线实验：

| 实验 | 目的 |
| --- | --- |
| `production_cap_240` | 模拟生产式行业 cap 后再取 240，用来量化行业 cap 损耗 |
| `no_industry_cap_240` | 同样取 240，但不做行业 cap，用来隔离行业 cap 影响 |
| `no_industry_cap_500` | 不做行业 cap，扩大到 500，用来观察 TopN 扩容影响 |

同时在报告中新增：

- `industry_cap_rejected_count`
- `topn_rejected_count`
- 每日漏斗诊断 `funnel_daily`
- 汇总漏斗诊断 `funnel_summary`

## 复现命令

运行目录：

```bash
cd /Users/xiong/Documents/SmartStock/.worktrees/funnel-recall-evidence/backend
```

完整不截断真实数据评估：

```bash
SMARTSTOCK_LOCAL_ENV_FILE=/Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env \
/Users/xiong/Documents/SmartStock/smartstock-web/backend/venv/bin/python \
  scripts/run_offline_recall_evaluation.py \
  --strategy-code trend_breakout \
  --risk-level medium \
  --start-date 2026-05-29 \
  --end-date 2026-06-17 \
  --horizons 3,5 \
  --top-k 3,5 \
  --commission 0.0003 \
  --slippage 0.001 \
  --include-baseline \
  --output-root /tmp/smartstock-funnel-recall-evidence-real-full-unbounded
```

关键输出：

```text
generated baseline: historical pick snapshots
generated recall_220_deep_150: offline market snapshots
generated recall_300_deep_300: offline market snapshots
generated recall_500_deep_500: offline market snapshots
generated production_cap_240: offline market snapshots
generated no_industry_cap_240: offline market snapshots
generated no_industry_cap_500: offline market snapshots
generated multi_channel_union: offline market snapshots
comparison_status: blocked
production_switch_ready: False
```

原始本地产物：

```text
/tmp/smartstock-funnel-recall-evidence-real-full-unbounded
```

这些 `/tmp` 明细产物未提交；本文档只保存可复查摘要。

## 实验结果

| 实验 | 样本行数 | 覆盖状态 | 覆盖交易日 | cap rejected | topn rejected | Precision@3 | Precision@5 | NDCG@10 | Top5 平均收益 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 217 | partial | 7 | 0 | 0 | 0.238095 | 0.214286 | 0.275239 | 2.294506 |
| recall_220_deep_150 | 1350 | partial | 9 | 0 | 33780 | 0.314815 | 0.300000 | 0.176673 | 3.689218 |
| recall_300_deep_300 | 2700 | partial | 9 | 0 | 33060 | 0.314815 | 0.300000 | 0.155354 | 3.689218 |
| recall_500_deep_500 | 4500 | partial | 9 | 0 | 31260 | 0.314815 | 0.300000 | 0.144982 | 3.689218 |
| production_cap_240 | 2160 | partial | 9 | 23658 | 9942 | 0.314815 | 0.300000 | 0.169098 | 3.689218 |
| no_industry_cap_240 | 2160 | partial | 9 | 0 | 33600 | 0.314815 | 0.300000 | 0.162762 | 3.689218 |
| no_industry_cap_500 | 4500 | partial | 9 | 0 | 31260 | 0.314815 | 0.300000 | 0.144982 | 3.689218 |
| multi_channel_union | 2503 | partial | 9 | 0 | 33257 | 0.314815 | 0.288889 | 0.169960 | 3.869818 |

## 第一性原理判断

智能选股漏斗的本质不是“少过滤”或“多展示”，而是同时满足三个条件：

1. **召回强势股**：未来真正强的票不能在早期被无证据硬规则剔除。
2. **压低噪音**：扩大候选池后，不能让低质量票大量挤入前排。
3. **排序前置收益**：未来强势股必须被排到 Top-K，而不是只出现在第 200 名以后。

本轮数据说明：

- 当前行业 cap 是一个粗暴损耗源，但直接取消 cap 并没有在这段样本中提升 Top-K 排序指标。
- 当前 `production_pre_score` 的排序能力不足。扩大到 500 后仍有强势票排在几百名，说明瓶颈已经从“召回数量”转向“排序因子”。
- 多通道召回方向值得继续，但需要重新设计排序融合，否则只能增加候选覆盖，不能稳定提升 Top-K。

因此，“把漏斗规则做好”的正确路线不是立刻把所有硬规则删除，而是：

1. 硬过滤只保留交易不可行和明显数据异常，例如 ST、退市、停牌、极端无流动性、无法成交。
2. 行业分散不应在召回前硬截断，应该改为排序阶段的软约束或组合层约束。
3. 召回池应多通道 union，并记录每只股票来自哪些通道。
4. 深度分析后的排序必须基于样本外验证有效的因子，而不是只靠当前 `pre_score`。
5. 页面可以展示更多研究候选，但 A/B 交易动作必须继续由证据门禁控制。

## 当前不允许做什么

- 不允许把本轮结果解释为生产策略已通过。
- 不允许仅凭 `Top5 平均收益` 改生产排序。
- 不允许直接删除行业 cap 后上线。
- 不允许把扩展候选展示成实盘买入建议。
- 不允许为了凑 A/B 数量降低交易动作门禁。

## 下一步

1. 补齐至少 30 个同口径全市场快照日期后，重跑本轮完整矩阵。
2. 在同一评估框架中加入“强势股召回率”：统计未来强势股在 `prefilter / recall / deep_analysis / top30` 各层的留存。
3. 为多通道 union 增加通道贡献诊断：每个通道召回多少未来强势股、多少噪音股。
4. 重新训练或重估排序因子，只允许进入离线实验，不直接切生产。
5. 当且仅当 Precision@K、NDCG@K、Top-K 收益、最大回撤和样本外覆盖同时通过，再提交独立生产策略切换方案。
