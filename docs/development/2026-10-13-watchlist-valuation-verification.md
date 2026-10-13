# 自选股持仓行情与日期修复

## 根因

1. `get_watchlist` 固定调用 `get_paper_portfolio(refresh_quotes=False)`，页面刷新没有获取行情，沿用买入时或此前的估值。
2. 没有最近动作记录的持仓，将 `updated_at` 作为 `created_at` 展示。原估值读取甚至在未获取行情时也把更新时间写成现在，造成美的显示为当天记录。
3. 同股票多条动作合并时读错日期层级，可能由旧动作覆盖新动作。

美的数据库本次建仓时间为 `2026-07-06 23:13:04`。交易流水同时保留 6 月买入、平仓以及 7 月重新买入，并未通过本次修复改写这些记录。

## 最小修复

- 持仓批量获取真实行情，校验有效价格、原始行情日期和官方最近交易日；保留来源与原始时间。
- 只有取得有效行情才更新估值。行情缺失、过期、日期未知、未来日期、价格异常或日历不可用时，现价/浮盈亏/风险显示未知，不回填买入价；旧估值单独标注。
- 持仓记录时间来自 `opened_at`；观察记录来自原动作时间。不再从估值更新时间推断建仓。
- 部分持仓行情未知时，总市值/总盈亏为未知，另返回已知部分与覆盖数，不把缺失按零收益统计。
- 持仓表与复盘共用同一响应中的估值，避免重复查询产生相互矛盾的数据。
- 页面可见时每 60 秒刷新，窗口重新获得焦点时刷新；并发加载去重。行情未核验时不从前端提交以成本价兜底的模拟平仓。
- 推荐分数/概率明确为保存快照，不是实时预测；旧持仓缺少对应快照时的最近快照回退保持原行为并披露。
- 未修改选股评分、模型、止盈止损比例、仓位或候选生成；未训练、推送、下单。

## 实测结果

2026-10-13 本地 API 与真实浏览器一致。行情来自 Tencent，时间为该日 16:14:30 至 16:14:57。

| 股票 | 持仓均价 | 行情价 | 100股账面浮盈亏 | 建仓时间 |
| --- | ---: | ---: | ---: | --- |
| 翰宇药业 300199 | 25.09 | 25.55 | +46.00 | 2026-10-12 23:24:45 |
| 中国银行 601988 | 7.03 | 7.07 | +4.00 | 2026-10-12 23:24:44 |
| 工商银行 601398 | 8.51 | 8.49 | -2.00 | 2026-10-12 23:24:42 |
| 美的集团 000333 | 80.64 | 82.79 | +215.00 | 2026-07-06 23:13:04 |

7个模拟持仓行情覆盖7/7；总成本20062元，市值20564元，账面浮盈502元（2.5022%）。这是原有口径的未实现价差盈亏，不是扣除所有成本的成交收益，也不保证可按报价成交。

更新前后只读核验：

- 64条 `paper_trades` 完整行按 id 聚合 MD5：`7476841ac59d8ec6376653762434f191`，一致。
- 持仓 symbol/qty/avg_price/cost_amount/opened_at/status 聚合 MD5：`e1031b7be21bb3a73c2c7b1fce3c5b4b`，一致。
- 仅刷新授权范围内的持仓估值，不修订历史成交价和时间；没有迁移。

## 验证与提交

后端 `backend` 目录：

```sh
TUSHARE_TOKEN= ./venv/bin/python -m unittest tests.test_watchlist_valuation tests.test_pick_freshness tests.test_non_trading_preparation_mode tests.test_core_logic tests.test_persistence tests.test_market_snapshot_history tests.test_data_sources tests.test_api_contracts -q
```

75项通过，mock/临时库测试；未运行全仓研究实验。前端 `frontend` 目录：

```sh
node --test tests/watchlistPresentation.test.mjs tests/smartScreenData.test.mjs tests/viteIsolation.test.mjs
npm run lint
npm run build
```

14项、lint、build通过，`git diff --check` 通过。浏览器打开 `/watchlist`，真实表格价格、时间、汇总均核对，0 errors；2条现有 React Router 提示。原始 API 响应、测试和台账对比保存在 ignored `runtime/watchlist-*`。

- `c9ccf87`：`coach_service.py`、`data_source_manager.py`、`test_watchlist_valuation.py`。
- `4ff94d8`：`Watchlist.jsx`、`watchlistPresentation.mjs`、`watchlistPresentation.test.mjs`。
- `6310202`：推荐快照来源文案与对应测试。

部署仍来自 `/Users/xiong/Projects/SmartStock/.worktrees/pick-calendar-refresh`，分支 `fix/pick-calendar-refresh`。后端已重启、健康检查通过；前端配置保持独立 Vite 缓存。未修改主工作区，原 `backend/.venv/` 未跟踪文件保留。

## 残余边界

本次核验的是服务返回的实际日期、来源与算术，不是双源行情逐笔对账。盘中同交易日的延迟报价会保留原始时刻，不能把“最近交易日行情”理解为零延迟。日历或行情失败时明确未知，不绕过验证。模拟交易成本/T+1执行与旧推荐快照完整性不在本轮修复范围，不能据本次估值展示宣称策略有效。
