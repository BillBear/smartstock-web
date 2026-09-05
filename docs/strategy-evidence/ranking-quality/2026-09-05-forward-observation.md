# 当前排序与A：前向观察已配置

## 范围与当前事实

本轮只把上轮的A假说接入独立观察工具，不改正式推荐。A沿用已保存的dd_prob升序；没有新增模型、阈值、仓位、止盈止损或其他实验。当前模型影响仍包含在既存输入中，不能将本比较解释成无ML反事实。

2026-09-05只读查询确认，最新候选仍为2026-07-20（50条）；7/10有50条、7/8有30条、7/7有25条。没有新的前向样本。本轮不启动应用、不生成正式候选，不把7月历史记录重新登记成9月观察。

## 实现的规则

- 固定身份：default / trend_breakout / medium。
- 仅本地Asia/Shanghai时间16:00之后、同一日期的既存候选可冻结；不按星期推断交易日。之后依据实际日K线验证日期。
- 每日首次采集冻结原始信号、当前顺序、A顺序、配置hash及采集时间。相同快照再次采集幂等；冻结后信号变化报错并保留原文件，不选择事后更有利的版本。
- 后续日期必须使用同一配置。成本缺失、身份混合、重复排名、dd_prob缺失或非法、文件hash失败时停止，不伪造或修复数据。
- 只比较当前顺序和A。采用上轮已修正的固定候选池、缺标签不补位、按日期配对、块bootstrap及贡献敏感性口径。观察结果永不自动晋级。
- 5/10/20日成熟由真实后续bar数决定，不能以日历经过若干天代替。只取TuShare日线及复权因子；没有观察样本时不调用provider。
- 日线价格是代理成交，不是可实现盘口成交；没有完整组合模拟、最低佣金和税费模型。配置冻结也不意味着历史模型或生产代码已被证明有效。

## 工具与运行资产

命令入口为 `backend/scripts/observe_ranking_forward.py`，支持capture、evaluate、status。运行根目录必须放在工作树外的持久研究目录。本机使用SmartStock工作区的runtime/strategy-quality/ranking-forward-v1，不把大数据提交Git。

目录中days为冻结观察，cohort为首次有效采集确定的配置；checks为采集检查；runs按日期和输入摘要分开保存标签及比较。旧标签缓存不覆盖，下一日期的标签使用新目录。异常文件不会被自动修复。

```bash
# 在backend目录，使用项目已有Python环境。
python scripts/observe_ranking_forward.py capture --root "$FORWARD_ROOT"
python scripts/observe_ranking_forward.py evaluate --root "$FORWARD_ROOT" --env-file "$ENV_FILE"
python scripts/observe_ranking_forward.py status --root "$FORWARD_ROOT"
```

## 自动观察

已在Codex当前任务创建每日北京时间17:10的heartbeat自动观察，名称“SmartStock A排序前向观察”，ID为`smartstock-a`，状态ACTIVE。任务检查研究分支及已验证提交后，先capture再evaluate。异常时停止；没有新增或状态未变时不重复汇报。

这个自动任务是消费者，不是选股生产者。需要应用正常运行并保存新日期候选，才可能产生新观察。若运行时路径消失、数据库不可连接或检查失败，自动任务不会创建worktree、启动服务或绕过错误。已确认自动任务创建成功，尚未经历首次定时执行，不能保证离线机器上的准点执行。

## 验证与交付

代码提交：`4b62ef5`。新增观察模块、CLI和11项相关测试；原实验模块仅增加A与baseline的对照封装。其他生产服务和前端未修改。

测试覆盖旧日期拒收、首次冻结及重复采集、冻结后变化、混合身份、配置漂移、缺失成本、hash损坏、重复排名、未成熟/成熟标签、缺标签不补位、只评估A及空状态不调用provider。

实际执行 `python -m unittest discover -s tests -v`：`Ran 219 tests in 5.697s; OK`，退出0。`git diff --check`通过。

真实CLI smoke checks：capture返回`before_capture_window`（执行时尚未16:00）；evaluate返回`waiting_for_forward_observations`、样本0。两者退出0，没有生成新的收益数字。只读PostgreSQL查询使用BEGIN READ ONLY并ROLLBACK。

下一次有意义的进展是冻结真实的新日期，再等待对应5/10/20日标签成熟；不是再训练模型或调整参数。本轮不合并、不推送、不晋级A。
