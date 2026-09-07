# 本地基础修复发布记录

## 范围和版本

用户已批准把基础修复落实到实际本地页面。本次不是策略晋级，也不证明选股准确率提高。

- 原运行代码：`836145b`。发布代码：`5f5337c`。
- 隔离分支：`release/local-reliability-v1`；主工作区通过 fast-forward 接入，没有推送。
- 选择性接入：`d26f314` 缓存 TTL/显式刷新、`53e42a5` 保存失败状态、
  `8c3c000` 陈旧/降级数据展示、`ef12c8c` 请求生命周期隔离、
  `2cea5f6` 双排名和非实证收益、`5f5337c` 快照来源与未知时刻提示。
- 不包含真实换手率替换、腾讯单位转换、ML trace、ML 融合调整或研究工具。
- 评分、排序、动作、评级、仓位、止盈止损及风险阈值未调整。保留原综合分展示顺序，
  另列原策略排名。当前全部 C/watch_only 时标题明确为“候选观察池（不是买入清单）”。

## 本轮验证

Python 使用既有 backend/venv；前端使用既有依赖，未升级依赖。

| 验证 | 实际结果 |
|---|---|
| 旧版本 `python -B -m unittest discover -s tests -v` | 169 tests，OK，3.699s |
| 将缓存回归测试在旧版本代码上执行 | 9 tests，3 failures/3 errors；复现 TTL、刷新和保存状态缺陷，旧版本无 force_refresh 参数 |
| 新版本 `python -B -m unittest tests.test_pick_refresh_cache tests.test_pick_request_lifecycle -v` | 26 tests，OK，12.410s；模拟超时有界返回 |
| 新版本 `python -B -m unittest discover -s tests -v` | 195 tests，OK，16.276s |
| 新增快照提示测试，先运行后实现 | 2 个新增测试因函数不存在失败；实现后通过 |
| `node --test src/pages/smartScreenPresentation.test.mjs tests/smartScreenData.test.mjs src/components/marketFactorPresentation.test.mjs` | 19 tests，全部通过 |
| `npm run lint` / `npm run build` | 均 exit 0；主工作区重新 build 也通过 |
| `git diff --check 836145b..release/local-reliability-v1` | exit 0 |
| AST 对照旧版本 CoachService | 82 个原有方法完全一致；变化限于初始化、缓存失效、请求入口，新增请求调度/发布辅助方法 |
| 旧/新版本固定输入低、中、高风险对照 | 三组完整 picks 相等；仅使用模拟输入和临时测试数据库 |

这些测试检验工程回归，不是股票收益实验。已有 Vite CJS API 弃用警告保留，未混入依赖升级。

## 实际部署验收

前后端仍在主仓库、8000/3601 端口运行，PostgreSQL 服务未重启。
后端使用既有配置和 uvicorn；本次指定 `--lifespan off`，跳过唯一的 startup 选股预热，
避免部署验收重新生成候选。该参数仅用于本次启动，没有修改 startup 源码或 start.sh；
以后使用普通 start.sh 重启仍会执行原预热。用户主动后台刷新入口保持可用。
附加运行响应头 `X-SmartStock-Release: 5f5337c`，便于区分文档 HEAD 与运行代码。

- `/health` 和 `/smart-screen` 均 HTTP 200。
- 只读 `GET /api/coach/picks/today?max_count=80&risk_level=medium&user_id=default&cached_only=true`，
  更新前后均为 2026-09-07、16 条；完整响应和全部 picks 字段分别完全相等。
- picks 的排序键规范 JSON SHA-256，前后相同：
  `e73adc97f0d8946dcc3cce7fcece053004149a5a872330377261263adfd4afc8`。
- 浏览器真实页面已看到“候选观察池（不是买入清单）”“本次读取未重新计算”、
  “生成时刻未记录”“市场快照保存时间：2026-09-07 21:48:52”和原始行情时刻未知提示。
- 表格显示“展示序号 / 原排名”“估计收益（非实证）”，综合分单位为“分”而不是“%”。
  中国长城仍为展示 4 / 原排名 5；世纪华通仍为 81.83 分、10.02%（估计）、C/0 仓位。
- 既有历史 `22/30`、`real_insufficient` 提示保持不变，未用研究重建样本替换正式证据。

原始只读响应、对照 JSON 及测试日志保存在工作区外层的
`runtime/local-reliability-release-20260907/`，不进入 Git。

## 边界与回退

没有在验收中点击后台刷新、模拟买入或其他交易按钮；真实刷新故障使用隔离测试验证。
未清理历史数据、未执行独立迁移、未运行新的正式回测或训练。
应用正常导入仍采用原 CoachStore 初始化流程，本次没有改变它。

行情原始时刻与旧候选精确生成时间依然缺失，因此不能宣称数据实时性已证实。
此次只交付运行可靠性和诚实展示；选股质量仍无已批准的新方案。

若需回退，保留本次提交，在干净工作区使用 `836145b` 的独立回退分支/检出目录启动旧服务，
继续使用原 PostgreSQL 和配置，再核对同一只读快照；不要 reset、删库或改写历史证据。
完整研究分支 `evaluation/ml-fusion-trace-e3-analysis` 仍保留在 `8162c96`，没有整体合并。
