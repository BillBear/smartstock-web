# TuShare 北交所详细资金流能力核验

## 结论

**当前凭据和当前 TuShare 数据契约下，不能为北交所补齐与现有详细资金流特征等价的历史数据。**

因此，`full-market-history-20260718-v2` 的详细资金流候选资产继续保持
`training_ready=false`。本次核验没有：

- 放宽全市场 `95%` 覆盖门槛；
- 删除北交所股票；
- 把缺失资金流填为零；
- 替换、训练或接入任何模型；
- 修改生产选股、排序、交易或页面逻辑。

这是数据源能力与字段语义的只读核验，不是“缺数据时降级”的授权。

## 已验证事实

探测日期为 `2026-07-17`，通过本地统一 secret 加载当前 `TUSHARE_TOKEN`；
命令输出和本文件均不包含 token。

| 调用 | 查询条件 | 结果 | 解释 |
| --- | --- | --- | --- |
| `daily` | `920953.BJ`, `20260717` | 1 行，交易所 `BJ` | 当前凭据可读取北交所日线。 |
| `moneyflow` | `trade_date=20260717` | 5,195 行，仅 `SH` / `SZ` | 当前详细资金流端点不返回北交所行。 |
| `moneyflow` | `ts_code=920953.BJ`, `trade_date=20260717` | 0 行 | 与全量查询的交易所范围一致。 |
| `moneyflow_ths` | `920953.BJ` 与 `000001.SZ` | 权限拒绝 | 当前凭据不能验证其北交所覆盖，也不能把它当作可用训练来源。 |
| `moneyflow_dc` | `920953.BJ` 与 `000001.SZ` | 权限拒绝 | 当前凭据不能验证其北交所覆盖，也不能把它当作可用训练来源。 |

TuShare 的官方 [`moneyflow` 文档](https://tushare.pro/document/2?doc_id=170)
将该接口描述为沪深 A 股个股资金流向；实测结果与该范围一致。官方
[`moneyflow_ths` 文档](https://www.tushare.pro/document/2?doc_id=348) 描述的是另一套
同花顺资金流字段与权限要求，不能在未取得权限、未核验历史覆盖和未完成字段语义映射前，
作为现有八个 `buy_*_amount` / `sell_*_amount` 字段的直接替代。

## 与已有全市场审计的关系

本次结果解释并确认了
[`2026-07-20-moneyflow-coverage-forensics.md`](2026-07-20-moneyflow-coverage-forensics.md)
中北交所 `0%` 详细资金流覆盖的根因：它是当前来源的产品范围，而不是：

- 单日分区拉取失败；
- 历史分区损坏；
- 行级 null 值处理错误；
- 可通过重复请求修复的暂态故障。

故不能把 `94.9229%` 覆盖解释为“接近可用”。在完整全市场训练契约下，缺失的是一个系统性
板块，而非可忽略的随机缺失。

## 阻断项与后续前置条件

当前详细资金流特征组仍有两个独立阻断项：

1. **来源覆盖阻断：** 当前授权的 `moneyflow` 无北交所覆盖；替代接口均尚无当前权限与历史
   覆盖证据。
2. **横截面计算阻断：** 已认证候选资产中的
   `flow_minus_industry_median` 在 symbol 分片内计算，未按完整交易日/行业 peer set 计算。
   即使获得新来源，也必须在新的、不可变资产中重算并重新通过 parity 认证。

允许继续的最小下一步是研究管线内部的“全局 peer set 特征物化”修复与 fixture parity 验证；
该工作不依赖放宽覆盖门槛，也不会使当前资金流特征重新启用。任何下列动作都需要单独提案、
数据契约和重建证据：

- 提升 TuShare 权限后重新核验 `moneyflow_ths` / `moneyflow_dc` 的字段、覆盖、历史稳定性、
点时性和许可；
- 接入另一项具有等价历史字段和北交所覆盖的数据源；
- 新建并验证明确的 SH/SZ-only 研究 universe（这是 universe 政策变化，不是数据清洗）。

## 可复现命令

以下命令只读访问数据源；执行时必须经环境加载 token，不能把 token 写入 shell 历史、日志或 Git。

```bash
set -a
source /Users/xiong/Documents/SmartStock/.local-secrets/smartstock.env
set +a

/Users/xiong/Documents/SmartStock/.venvs/ml-py313/bin/python - <<'PY'
import os
import tushare as ts

pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])
for endpoint, params in (
    ("daily", {"ts_code": "920953.BJ", "trade_date": "20260717"}),
    ("moneyflow", {"trade_date": "20260717"}),
    ("moneyflow", {"ts_code": "920953.BJ", "trade_date": "20260717"}),
):
    frame = pro.query(endpoint, **params)
    print(endpoint, params, len(frame))
PY
```

替代端点探测必须捕获并脱敏权限错误；权限拒绝本身是有效的 `not_available_under_current_credential`
证据，不能被解释为数据值为零。
