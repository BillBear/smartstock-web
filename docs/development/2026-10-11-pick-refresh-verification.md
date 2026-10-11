# 候选日期与刷新修复：本地验收

验收日期：2026-10-11（北京时间）。只修日期、数据新鲜度与刷新，不调整选股策略。

## 根因与边界

- 原工作日判断不识别国庆休市，候选日期可写成系统日期而非行情日期。
- 原非交易日阻止刷新，完整候选缓存也未正确遵守 TTL。
- 页面读取时间曾标作“当前数据时间”，无法代表行情实际时间。
- 改用 TuShare `trade_cal` 的完整官方日历；未知或失败不回退到星期判断。
- 强制刷新清除相关缓存，校验全市场行情、候选报价和候选日线日期；旧日期或缺失日期拒绝更新，不伪造时间。
- 周末允许按最近有效交易日重新计算观察候选，但不开启模拟买入。历史查看仍只读。
- 生成时间、行情时间、快照保存时间和页面读取时间分开显示。

## 实际部署与数据

- URL：<http://localhost:3601/smart-screen>；后端 `/health` 返回 healthy。
- 部署工作区：`/Users/xiong/Projects/SmartStock/.worktrees/pick-calendar-refresh`。
- 分支：`fix/pick-calendar-refresh`，基于原部署 `616ce60c06ef`，未合并、未推送。
- 使用原 PostgreSQL 集群、原模型目录和已有环境的本地链接，没有重建数据库。
- 官方最近有效交易日：2026-10-09；周日 2026-10-11 不当作交易日。
- 实际行情：5,224 条，报价时间均为 2026-10-09 16:14:00 至 16:15:00。
- 新候选：22 只，全部 `quote_trade_date=2026-10-09`；生成时间 2026-10-11 22:34:59。
- 当前缓存读取 `freshness_status=current` 指匹配最近交易日，不表示实时行情。
- 72 只深度分析全部完成，无超时；原策略闸门保留，当前结果不可执行。
- 旧记录（日期不晚于 2026-10-05）更新前后均为 1,668 条，按 pick_id 排序 snapshot_json 聚合 MD5 均为 `2f97421e98ff8beaf3e425892ea10e30`。
- 原主工作区未改源码，原有未跟踪 `backend/.venv/` 保留。

这是今天重算的观察结果，可能包含今天已知的其他策略输入，不能当作周五事前信号或 PIT 回放。本次不证明策略有效、收益提高或报价以外全部因子的准确性。

## 验证

后端工作目录 `backend`：

```sh
TUSHARE_TOKEN= ./venv/bin/python -m unittest tests.test_pick_freshness tests.test_non_trading_preparation_mode tests.test_core_logic tests.test_persistence tests.test_market_snapshot_history tests.test_data_sources tests.test_api_contracts -q
```

67 项通过。测试使用 mock/临时存储，不在生产库运行测试写入。

仓库根目录：

```sh
node --test frontend/tests/smartScreenData.test.mjs frontend/src/pages/smartScreenPresentation.test.mjs frontend/src/pages/stockDetailPresentation.test.mjs frontend/src/components/aiDecisionPresentation.test.mjs
git diff --check
```

前端 13 项通过；`frontend` 下 `npm run lint`、`npm run build` 通过。已有 LibreSSL/FastAPI/Vite 弃用警告不影响本轮通过。未声称运行全仓全部研究测试。

使用 Playwright 打开真实页面，确认最近交易日、报价时间、生成时间、更新按钮及“页面读取时间”标签；控制台 0 errors、2 warnings。页面截图与响应保存在 ignored `runtime/`：

- `pick-refresh-result.json`：首次真实 POST 刷新响应；其中辅助 universe 日期显示问题随后修正，未改写这份原始响应。
- `pick-refresh-final-read.json`：修正后真实 API 回读，候选及市场快照日期一致为 10 月 9 日。
- `.playwright-cli/page-2026-10-11T14-42-26-602Z.png`：部署后页面截图。

对 `616ce60` 做 AST 比较：候选池规则、分数校准、风险筛选、决策、交易计划、策略配置清洗，以及 `_build_pick` 分析后的评分/ML/交易规则代码均保持一致。日期校验会拒绝过期输入，这是本轮授权的数据正确性变更。

## 文件与提交

- `2c2c865`：`main.py`、`coach_service.py`、`data_source_manager.py`、`tencent_service.py`、新增 `pick_freshness.py`，以及 core/non_trading/pick_freshness 测试。
- `05aac42`：`SmartScreen.jsx`、`smartScreenData.mjs` 及对应前端测试。
- `ca4313c`：刷新响应辅助日期与真实行情日期对齐，补回归测试。
- `dc909f7`：补完整候选缓存过期测试。
- `3400898`：页面读取时间标签修正及回归测试。

本地 `.git/info/exclude` 仅补充共享运行数据链接的精确忽略路径，未提交运行资产、密钥或数据库。

## 运维与残余风险

- 当前服务来自上述修复工作区，请勿删除该工作区；本地重启应从该目录使用原生命周期脚本。
- 退出 screen 后仍须检查 8000 端口；本次发现旧 uvicorn 子进程可能残留，通过确认 PID/cwd 后 SIGTERM 再启动完成切换。未扩大范围修改生命周期脚本。
- 日历接口不可用、任一行情日期不匹配或候选日线未更新时会拒绝刷新，保留历史数据并显示错误，不以旧数据冒充成功。
- 恢复旧代码需明确停止当前前后端、从原主工作区启动并核验版本；不会删除本次新快照。不建议回退到已知存在日期错误的旧行为。
- 未训练、修改模型/阈值/止盈止损/仓位，未调整排序；没有推送或合并。
