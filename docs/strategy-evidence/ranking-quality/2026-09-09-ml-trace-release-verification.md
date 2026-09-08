# ML 旁路记录本地发布候选核验

日期：2026-09-09。状态：最小补丁验证通过，**未部署**。这不是策略效果报告或新的准入门禁。

## 范围与起点

- 部署工作区代码起点：`e441b17e302e1b4977a89b60026210428902ef0b`。
- 发布候选分支：`release/ml-trace-candidate`，复用既有隔离 worktree；代码提交 `77abc0e`。
- 原主计划依据：`fix/e3-trace-verification` 上的 `docs/superpowers/plans/2026-09-05-swing-selection-quality-master-plan.md` 第 6 节、Task 6 的 ML 最小补证。
- 从研究分支选择性接入既有 `ml_fusion_trace_v2` 记录，没有整体合并研究分支。只修改 `coach_service.py`，新增 `test_pick_ml_trace.py`，扩展 `test_pick_refresh_cache.py`。
- 不改 ML 模式、融合权重、候选池、排序、评分、action、评级、仓位、止盈止损、数据源、API、前端、数据库结构或回测。已有缓存不清空、旧快照不回填、正式候选不重建。

## 发布前实际发现的故障

研究版本把 feature schema 提取和模型数值记录放在原预测 try/except 内。故障注入证实：

| 注入位置 | 旧研究实现 | 发布候选 |
|---|---|---|
| `_trace_feature_names` 抛异常 | 模型调用 0 次，原调用被跳过 | 原模型仍调用 1 次；仅记录 trace_error |
| `_trace_optional_float` 抛异常 | 原融合未执行，固定样例 up_prob 从 0.7615 退为 0.8 | 融合结果不变；仅记录 trace_error |
| trace 含不可 JSON 序列化对象 | 可能破坏后续快照保存 | 在独立记录边界转换为 trace_error |

修复将旁路提取和 JSON 可序列化检查移至原预测/融合处理之后，使用独立异常边界。真实模型失败仍保持原有处理，同时标记 prediction_error；空预测标记 prediction_unavailable。异常只保存类型，不保存异常文本、密钥或特征值。此处修复优先于任何部署，不能把上一版旁路代码直接上线。

校准记录包括截断前完整 symbol 集合、校准时 action/market state 和前后总分；最终 gate 记录 action/grade/executable/real_money_allowed。缺少校准池或模型身份的旧 trace 仍不能成为 E3 证据。保存沿用原 snapshot_json，不需要迁移。

## 独立部署版本对照

从 Git 读取固定 baseline 的真实 CoachService 类 AST，与发布候选使用相同依赖、相同合成行情和假模型服务。未导入 app.main，store=None，网络连接被断言禁止；没有真实模型推理或训练。

矩阵：3 种风险等级 × 3 种市场状态 × 2 种策略 × 6 种模型状态（未配置、正常、空结果、异常、缺字段、裁剪边界）= 108 个情形。结果：

- 54 个趋势策略情形共比较 108 条候选，删除新增顶层 trace 后，**完整 JSON 字节投影和模型/特征调用次数完全一致**。
- 54 个回调策略情形在该合成上涨序列上均被原规则拒绝，新旧版本都不出候选；不能据此声称验证了回调策略成功出池路径。
- 非空情形同时经过校准、风险排序、rank_no、交易计划附加。仅原来的 3 个方法 AST 有旁路增量，其余原有 Coach 方法 AST 相同；新增 2 个 trace helper。
- baseline 源码 SHA-256：`6ae53334fc84ab7cdde427b538ff7999241893f7b01b152b7f1a962ba3cdbc7f`。
- 两次结果相同，0 mismatches，结果 SHA-256：`7200e0d4868ab49a0fa5df5506d317cd03162a41ec0e1f9188b8903fd76dd0db`。

复核脚本保存在项目外层的 ignored 运行产物目录 `runtime/ml-trace-release-20260909/verify_parity.py`，SHA-256：`208abc9aaed2b67a4920f8db5b22d3ef5bf2ad56d0b6fc3571f5149ff592783f`。从候选 worktree 的 backend 目录设置 PY 为现有虚拟环境 Python、EVIDENCE 为该运行产物目录后执行：

```bash
PYTHONPATH=. "$PY" -B "$EVIDENCE/verify_parity.py"
```

## 测试与边界检查

先在部署基线上运行移植后的 trace 测试，3 项因 trace 不存在失败；接入后通过。新增 helper 故障注入的 2 个反例在旧研究实现上失败，隔离异常边界后通过。

```bash
"$PY" -B -m unittest tests.test_pick_ml_trace tests.test_pick_refresh_cache tests.test_pick_request_lifecycle tests.test_core_logic tests.test_strategy_contracts tests.test_persistence tests.test_data_sources tests.test_api_contracts -v
```

实际结果：`Ran 74 tests in 12.950s / OK`。覆盖正常/异常 trace、推理只调用一次、候选投影、缓存不重建、保存失败可见、并发请求生命周期及临时 SQLite JSON 往返。超时用例为有界假 provider，约 12 秒；预期保存异常日志不是忽略测试失败。

从仓库根目录执行 `git diff --check` 无输出。下列路径相对 baseline 的 diff 为零：ml_model_service.py、data_source_manager.py、tushare_service.py、tencent_service.py、coach_store.py、app/main.py、frontend。原运行分支保持干净，未改其文件或运行进程。

未跑会导入 app.main 的完整测试发现；未运行前端构建（前端无改动）。上述 SQLite 仅是隔离测试库，不能冒充真实 PostgreSQL 验证。没有访问实际 PostgreSQL、清理缓存、重启应用、生成正式候选、回测或训练。

## 落地与剩余限制

本补丁完成的是“只记录、不干预”的发布前核验，不证明 ML 有效，更不证明选股收益提升。当前页面仍运行旧版本，不会因研究或候选分支提交自动获得 trace。

后续本地部署需明确授权，只引入 `77abc0e` 这一最小代码提交，而不是整个研究分支。部署时应先固定 cached-only 响应，避免启动预热或 force refresh 触发新候选；发布前后对比既有候选的完整投影、健康状态与读取来源。自然生成新候选后，再只读核对 PostgreSQL 中真实 trace。新候选被展示截断、模型字段缺失或尚无成熟标签时，E3 仍应 unavailable，不能补造隐藏候选或旧融合记录。

回滚仅需在发布分支反向 revert 此代码提交；JSON 新字段向后兼容，不删除已保存证据，不改数据库结构，不改模型配置。尚未执行任何合并、部署或回滚。
