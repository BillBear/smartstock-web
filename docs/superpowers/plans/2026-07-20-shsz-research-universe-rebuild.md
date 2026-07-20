# SH/SZ 两年研究 Universe 重建计划

## 决策与边界

用户已明确：下一轮离线 ML 研究不纳入北交所股票。本计划将其定义为新的、固定的
`shsz_a_share_v1` **研究 universe**，而不是对现有全市场资产的缺失值修补。

- 包含：历史时点上交易代码后缀为 `.SH` 或 `.SZ` 的 A 股普通股票。
- 排除：`.BJ`、无法确定交易所的行、非股票指数或 ETF 代码。
- 不修改：生产候选池、CoachService、生产选股排序、买卖、止盈止损、仓位、UI。
- 不复用：`full-market-history-20260718-v2` 中已物化的特征列或训练 parquet。
- 保留：全市场原始分区、旧数据集、失败报告和 SHA256；它们是不可变审计证据。

## 顺序与门禁

### R0: Universe 契约与来源认证

1. 在 raw `daily`、`daily_basic`、`adj_factor`、`stk_limit`、`moneyflow` 分区仍保留
   `ts_code` 后缀时完成 SH/SZ 过滤；禁止在 symbol 标准化后按前缀猜测。
2. 以过滤后的历史 `stock_basic` L/D/P 上市区间构造每个交易日的预期 SH/SZ 活跃 universe。
3. 分别记录：预期活跃数、daily 实际数、daily 覆盖、详细资金流覆盖、缺失 symbol、交易所分布。
4. 门禁：每个接受训练日的 `daily / historical_expected >= 95%`；详细资金流覆盖 `>= 95%`；
   不允许任何 BJ 或未知交易所行进入。
5. 输出不可变 `universe_contract.json`、每日覆盖 CSV、缺失原因 CSV、源 manifest SHA256。

### R1: 新原始派生面板与样本认证

1. 从 R0 已认证的原始分区新建 `full-market-history-shsz-<date>-v1`，不重写原 run。
2. 重建调整后 OHLC、next-open 可交易性、涨跌停、停牌、历史 ST、行业时点和上市年龄。
3. 重新构建成本后 10 日 alpha、独立 severe-risk 标签和五折/20 日 embargo/20% 股票 holdout。
4. 新 dataset ID 必须包含：源 manifest、universe contract、代码、标签 schema、split schema、
   feature schema 的 SHA256。
5. 门禁：重复键为零、无未来字段、标签窗口完整、样本/标签/切分认证为
   `certified_research_sample`；否则停止。

### R2: 新特征资产与 parity

1. 用已修复的全局 `trade_date + industry_l1` peer set 重算 `flow_minus_industry_median`。
2. 详细资金流只在 R0 覆盖门槛通过后注册；绝不以缺失 flag 代替观察值。
3. 至少在三个固定交易日验证 raw -> offline matrix -> online provider 的同字段同单位一致性，
   并确保输入没有任何未来行。
4. 门禁：字段覆盖、离线/在线 parity、全局 peer parity 全部通过；否则不进行特征实验。

### R3: 预注册特征证据和训练

依次、互不混合地评估 H1 市场/行业、H2 详细资金流、H3 公告时点基本面。每个假设使用相同
A/C OOF key set、固定 baseline、五折 walk-forward 和股票 holdout。只有任一特征组通过既定的
Precision@5、NDCG@10、Top5 净收益、bootstrap 下界和 unseen-stock retention 门槛，才可运行
有界 ranker；否则写失败结案，不换模型碰运气。

## 验收与禁止事项

- R0-R2 的每个产物均为新路径、新 run ID、新 hash，不能覆盖旧资产。
- 北交所排除必须在 manifest、每日统计和特征字典中可见。
- 不得因排除北交所降低 `95%` 覆盖门槛、改变标签或放宽 split。
- 不得把 SH/SZ 研究结论表述为全 A 生产模型结论。
- 任何 ranker、shadow 或 production 接入仍受 2026-07-18 恢复计划的 G4-G8 门禁约束。
