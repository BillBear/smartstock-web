# SmartStock Web Agent Governance

本文件适用于当前 `smartstock-web` 仓库根目录及其所有子目录。它继承并补充
`/Users/xiong/Documents/SmartStock/AGENTS.md` 的工作区治理规则；如有冲突，执行更严格、
更安全的规则。

## 项目边界

SmartStock AI 是本地运行的 A 股投资决策辅助系统。本仓库中的任何文档、代码、测试和演示内容
都不得暗示保证收益、确定性推荐或实盘必然有效。本项目仅供学习和研究使用，不构成投资建议。

## Worktree 与提交纪律

- 每个任务必须在独立分支或 worktree 中完成，并在开始前运行 `git status --short --branch`。
- 本仓库的 worktree、分支命名、脏状态处理、提交范围和验证要求见
  `docs/development/worktree-and-commit-policy.md`。
- 当前主工作区 `/Users/xiong/Documents/SmartStock/smartstock-web` 可能存在无关未提交改动；
  不要在该目录中处理本仓库任务，也不要回滚、清理或暂存他人的改动。
- 禁止在混合工作状态下使用 `git add .`。只暂存本任务需要的明确路径，并在提交前检查
  `git diff --cached --name-only`。

## 策略与 baseline 门禁

- 无证据禁止改策略。没有测试和回测证据时，不得修改选股、候选池、排序、评分、买卖、仓位、
  风险闸门、概率模型、回测执行模型或任何会改变用户看到的推荐结果的逻辑。
- 策略影响变更必须提交可复现的 baseline 对比和验证输出，且策略证据文档必须与策略代码变化
  分层提交。
- 文档、工程稳定性和评估系统搭建任务不得顺手调整策略参数，也不得改变当前 stock-picking 结果。

## ML 研究台账与产物

- 正式 ML 数据采集、训练、评估、模型卡或候选冻结只能从
  `docs/governance/ml-research-ledger.md` 明确登记的研究分支启动；未登记分支只允许检查或一次性诊断。
- 正式运行必须引用不可变 `dataset_id`、原始/派生清单哈希、特征/标签/切分哈希、代码提交和研究假设；缺任一项即为 `preflight_failed`，不得继续训练。
- 原始数据、Parquet 面板、模型二进制、OOF 预测和运行产物属于 `ML_ASSET_ROOT` 管理的本地研究资产，不得提交 Git，也不得在 worktree 的 `runtime/` 目录中作为唯一权威副本。
- `research_only`、`research_only_failed_gate` 和 `shadow_candidate` 模型不得改变 CoachService 的分数、排序、动作、仓位或风险闸门。只有满足完整准入证据并经人工批准的 `production_candidate` 才能进入独立接入任务。

## 分层修改

- 前端、后端、数据服务、策略引擎、回测引擎、监控告警、数据库迁移、文档和策略证据应分层规划、
  分层验证、分层提交。
- 路由层不承载复杂策略规则；前端只负责展示、交互和 API 调用呈现，不实现策略决策。
- 数据服务必须清楚区分真实数据不可用和 mock 数据，禁止用 mock 数据冒充真实行情或策略输入。

## 完成要求

- 每个产生文件改动的任务必须有独立提交，提交信息清楚说明范围，例如
  `docs: add worktree commit policy`。只做 review、research、status-only 或其他不产生文件改动的任务时，
  不要求创建提交；完成说明仍需记录实际检查或验证输出。
- 完成说明必须列出改动文件、验证命令、关键输出、提交 SHA 和未解决风险。
- 在说“完成”“已修复”或“可合并”前，必须运行与改动范围匹配的验证命令并记录输出。
