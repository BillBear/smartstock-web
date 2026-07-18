# 资金流数据来源契约

## 目的

资金流接口的空响应、权限不足和网络错误不得被转换成看似真实的主力净流入。候选池、模型训练和页面输出必须能区分真实观测、估算、代理和缺失。

## 字段

所有资金流结果必须携带以下字段：

| 字段 | 含义 |
| --- | --- |
| `data_source` | 小写来源标识，例如 `tushare`、`akshare`、`quote_amount_pct_change` 或 `none`。 |
| `data_quality` | `observed`、`estimated`、`proxy` 或 `missing`。 |
| `as_of_date` | 观测数据对应的最近交易日；不可用时为 `null`。 |
| `fallback_reason` | 非观测数据的原因；观测数据为 `null`。 |

## 质量语义

- `observed`：来源接口返回的实际资金流字段。只有这一类可用于标为“观测资金流”的训练特征。
- `estimated`：由价格、成交额等推导出的诊断估算。必须由调用方显式设置 `allow_estimated=true`，不得进入候选评分或训练标签。
- `proxy`：候选批处理由 `成交额 * 涨跌幅 / 12` 构成的低成本资金强弱代理。它可以保留为明确命名的代理特征，但不是观察到的资金流。
- `missing`：接口权限不足、空响应或错误后没有可观测数据。不得转换成零流入、零流出或方向性结论。

## 调用规则

1. `TuShareService.get_money_flow(..., allow_estimated=False)` 是默认路径；空响应或错误返回 `missing`。
2. `DataSourceManager` 仅缓存可观测数据，诊断调用的估算数据使用独立缓存键。
3. 智能选股批处理保留 `proxy` 的来源和质量标记；`money_flow_observed_feature_eligible=false`。
4. 当资金流为 `missing`，个股资金流接口必须返回“数据不可用”，不能生成净流入、净流出或看涨/看跌结论。

## 非目标

本契约不修改资金流评分权重、候选排序、买卖门槛、止盈止损或仓位参数。任何后续将数据质量改变接入策略的工作，必须先按项目治理要求提供 baseline、样本外和 walk-forward 证据。
