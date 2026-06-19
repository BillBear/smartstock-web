# Worktree and Commit Policy

本政策适用于 `smartstock-web` 仓库的所有任务，补充上层
`/Users/xiong/Documents/SmartStock/AGENTS.md` 和本仓库 `AGENTS.md`。目标是让每个任务、
每个提交和每次验证都可追踪、可复现、可审查。

## Worktree 选择规则

本政策适用于所有 `smartstock-web` 任务，不绑定某个固定 worktree。开始任务时按以下顺序选择工作区：

- 如果任务说明提供了干净 worktree，使用该 worktree，并先运行 `git status --short --branch` 确认。
- 如果任务没有提供 worktree，在 `/Users/xiong/Documents/SmartStock/.worktrees/<branch-slug>` 下创建新的
  linked worktree，或使用负责人批准的外部 worktree 路径。
- 不要在已有 worktree 内再创建嵌套 worktree。
- 主工作区 `/Users/xiong/Documents/SmartStock/smartstock-web` 可能存在与当前任务无关的脏改动；
  不要在主工作区修改、暂存、清理、stash 或回滚任何文件，除非任务明确指定使用该目录且状态已确认干净。

## 当前审计稳定化阶段约定

本节只适用于当前 `audit/stabilization-phase-1` 审计稳定化阶段任务，不能作为其他任务的默认
worktree 配置。

本阶段提供的 worktree 位于：

```text
/Users/xiong/Documents/SmartStock/.worktrees/audit-stabilization-phase-1
```

分支为：

```text
audit/stabilization-phase-1
```

执行本阶段任务时，只能在上述 isolated worktree 中工作；其他任务应遵守上一节的 Worktree
选择规则。

## 分支命名规则

分支名必须表达任务类型和范围，使用小写 kebab-case。推荐格式：

```text
<type>/<scope-or-topic>
```

常用 `type`：

- `docs/`：文档、治理、流程说明。
- `backend/`：后端 API、服务、测试，不含策略参数调整。
- `frontend/`：前端页面、组件、样式或前端测试。
- `migration/`：数据库迁移、回滚说明和兼容文档。
- `strategy-evidence/`：策略 baseline、回测证据、评估报告，仅限证据文档。
- `audit/`：审计、稳定化、评估系统建设。
- `fix/`：明确缺陷修复。

示例：

```text
docs/worktree-commit-policy
backend/health-check-stability
frontend/coach-empty-state
migration/coach-store-index
strategy-evidence/baseline-2026q2
audit/stabilization-phase-1
```

## Worktree 路径约定

如果任务说明没有提供 worktree，优先使用项目工作区下的 `.worktrees/<branch-slug>`：

```text
/Users/xiong/Documents/SmartStock/.worktrees/<branch-slug>
```

其中 `<branch-slug>` 通常等于分支名去掉类型前缀后的主题，或使用完整主题的 kebab-case。
也可以使用负责人批准的外部 worktree 路径。
不要在已有 worktree 内再创建嵌套 worktree。

开始任务前必须确认当前位置和分支：

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
```

如果 `git rev-parse --git-dir` 与 `git rev-parse --git-common-dir` 不同，说明当前目录已经是
linked worktree；继续使用当前 worktree，不要再创建新的 worktree。

## 已有脏状态处理

开始任何任务前运行：

```bash
git status --short --branch
```

处理规则：

- 如果工作区干净，可以开始任务。
- 如果只有本任务相关改动，先理解来源，再继续。
- 如果存在无关脏改动，不要复用该工作区继续开发；改用干净 worktree，或让负责人先处理。
- 不要使用 `git reset --hard`、`git checkout --`、`git clean`、`git stash` 清理他人的改动，除非负责人明确要求。
- 如果任务过程中出现与本任务无关的改动，不要暂存，不要提交，并在完成说明中标明。

## 提交范围规则

每个提交只包含一个清晰主题，并且只覆盖一个主要层级。文档、后端、前端、迁移、策略证据、
策略代码、回测引擎和监控口径不得混在同一提交里。

提交前必须检查：

```bash
git status --short
git diff --name-only
git diff --cached --name-only
```

禁止在混合工作状态下使用：

```bash
git add .
```

也不要用 `git add -A` 来绕过范围检查。应使用明确路径或交互式暂存：

```bash
git add README.md docs/development/worktree-and-commit-policy.md
git add -p backend/app/main.py
```

策略相关文件更严格：任何会改变选股、排序、评分、买卖、仓位、风险、概率模型或回测结论的
改动，必须先有 baseline 证据、拒绝标准和对应验证输出。只做工程稳定性或评估系统搭建时，
不得修改策略参数，也不得改变当前 stock-picking 结果。

## 提交示例

document-only 提交：

```bash
git add AGENTS.md README.md docs/development/worktree-and-commit-policy.md
git commit -m "docs: add worktree commit policy"
```

backend-only 提交：

```bash
git add backend/app/main.py backend/tests/test_health.py
git commit -m "backend: stabilize health check contract"
```

如果后端改动触碰策略引擎、回测执行、概率模型或用户可见推荐结果，不能按普通后端提交处理；
必须拆出策略影响任务并附 baseline 证据。

frontend-only 提交：

```bash
git add frontend/src/pages/Coach.jsx frontend/src/components/CoachStatus.jsx
git commit -m "frontend: clarify coach status empty state"
```

migration-only 提交：

```bash
git add backend/scripts/20260619_add_coach_index.sql docs/v1-investment-coach/02-data-model.md
git commit -m "migration: add coach store index migration"
```

strategy-evidence-only 提交：

```bash
git add docs/strategy-evidence/2026-06-19-baseline.md
git commit -m "docs: record 2026 q2 strategy baseline"
```

strategy-evidence-only 提交只能记录 baseline、样本切分、执行假设、指标、拒绝标准、复现命令和关键输出；
不得同时修改策略参数或回测引擎代码。

## 验证与完成说明

每个任务必须运行与范围匹配的验证命令，并在完成说明中记录命令和关键输出。

文档和治理任务至少运行：

```bash
git status --short --branch
find . -maxdepth 3 -name AGENTS.md -print
rg -n "worktree|git add|策略|baseline|验证" AGENTS.md docs/development/worktree-and-commit-policy.md README.md
```

后端任务按范围运行：

```bash
cd backend
python -m unittest discover -s tests
```

前端任务按范围运行：

```bash
cd frontend
npm run lint
npm run build
```

策略影响变更必须额外运行对应回测和 baseline 复现命令，并记录样本内、样本外、walk-forward、
交易成本、滑点、最大回撤、收益回撤比、Precision@K、NDCG@K 等关键输出。验证失败或 baseline
缺失时，不得声明完成或可合并。
