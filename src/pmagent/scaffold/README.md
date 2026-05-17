# PM Agent 数据目录

这个 README 会被 `pmagent init` 复制到运行时数据目录根部。
它的职责不是解释仓库代码，而是帮助你理解 `<data_dir>/` 的结构、当前状态入口，以及推荐的 CLI 使用方式。

## 文档定位

这份文档是运行时数据目录说明，不是 Agent 的最终真相源。

真相源优先级：

1. CLI / Python 实现
2. `config/agent-workflow.yaml`
3. `AGENTS.md`
4. 运行时状态文件
5. 面向人的说明文档

## 关键位置

- `config/projects.json`：active project / workspace 注册表
- `config/agent-workflow.yaml`：面向 Agent 的结构化执行合同
- `projects/`：长期项目级知识
- `workspaces/`：单个需求级工作区
- `memory/`：全局记忆和提升候选
- `skills/`：由 `pmagent init` 同步进来的内置 skills
- `templates/`：由 `pmagent init` 同步进来的模板
- `ops/`：weekly / quality 等运维产物

## 数据目录结构

```text
<data_dir>/
  AGENTS.md
  CLAUDE.md
  MEMORY.md
  GOAL_STATE.md
  README.md
  .env
  .env.example
  .pmagent-version
  config/
  memory/
  projects/
  workspaces/
  skills/
  templates/
  ops/
  cache/
  ppt/
```

典型的 workspace：

```text
workspaces/<workspace>/
  Requirement.md
  workspace-summary.md
  .pmagent/current-state.json
  context/
  research/
  strategy/
  decisions/
  prd/
  candidate-updates/
  maintenance/
  exports/
```

其中：

- `context/clarifying-log.md`：clarifying 阶段的全量原始问答日志
- `research/research-log.md`：researching 阶段的全量原始记录日志
- `Requirement.md` / `workspace-summary.md` 负责结论与状态，不替代 phase raw log

典型的 project observation：

```text
observations/<project>/
  index.json
  policy.json
  state.json
  files/
  runs/
```

## init 与 upgrade 的边界

`pmagent init` 会：

- 创建运行所需目录
- 写入全局 `data_dir`
- 复制托管 scaffold 文件
- 创建可提交的 `.env.example` 配置样例；仅在 `.env` 缺失时创建本机私密 `.env`
- 同步打包内置的 `skills/` 和 `templates/`

`pmagent init` 不会直接创建：

- `observations/<project>/`
- `workspaces/<workspace>/candidate-updates/`
- `workspaces/<workspace>/maintenance/`

这些目录由 `workspace-init` 或 observation 初始化逻辑按需创建。

`pmagent upgrade` 会刷新托管 scaffold、配置模板、`.env.example` 和打包内置 assets，但会保留用户手工新增的 skills / templates / 数据文件；`.env` 作为本机私密配置不会被覆盖。

## 当前状态入口

推荐的 workspace 状态入口有两个：

- `workspaces/<workspace>/workspace-summary.md`
- `workspaces/<workspace>/.pmagent/current-state.json`

它们的职责：

- `workspace-summary.md`：给人和 Agent 看的压缩摘要
- `.pmagent/current-state.json`：给 CLI / shell / 自动化读的结构化状态

它们不替代：

- `Requirement.md`
- `research/`
- `context/`
- `decisions/`
- `prd/`

## 推荐的前门命令

当前实现里，推荐优先从这些命令进入：

```bash
pmagent status
pmagent route
pmagent review
pmagent start
pmagent next
pmagent resume
```

按 phase 进入的专用入口：

```bash
pmagent clarify status
pmagent clarify answer --answer "..."
pmagent clarify set-scores --patch-file <file>
pmagent research start --workspace <workspace> --json
pmagent research status
pmagent research note --summary "..."
pmagent research set-scores --patch-file <file>
pmagent prd status
pmagent prd review
pmagent prd challenge
pmagent prd init-draft
```

## 推荐的 observation 闭环

### 初始化 workspace

```bash
pmagent workspace-init --project <project> --workspace <workspace>
```

默认行为是：

- 初始化 workspace scaffold
- 初始化 observation scaffold
- observation cadence 默认为 `manual`
- 不自动创建定时任务
- 如果用户还没做出最终决策，observation policy 继续保持 `unresolved`
- 如果用户只是暂缓，仍然保持 `unresolved`
- 只有用户明确拒绝 observe 时，才把 policy 视为 `manual`

### 如需调度，再显式开启

```bash
pmagent observe enable --project <project> --cadence daily --confirm-cadence
pmagent observe set-cadence --project <project> --cadence weekly --confirm-cadence
pmagent observe disable --project <project>
```

当前调度后端：

- Windows：Task Scheduler
- macOS：launchd
- Linux：systemd user timer

### 每次进入交互前先 audit

```bash
pmagent observe audit --workspace <workspace> --run-catch-up --json
```

### 有 backlog 时先 review

```bash
pmagent observe review --workspace <workspace>
pmagent observe accept --workspace <workspace> --card <observation-id>
pmagent observe reject --workspace <workspace> --card <observation-id>
pmagent observe snooze --workspace <workspace> --card <observation-id>
```

### 已接受信号再进入 maintenance

```bash
pmagent observe maintenance-status --workspace <workspace>
pmagent observe draft-maintenance --workspace <workspace>
pmagent observe apply-maintenance --workspace <workspace>
```

其中：

- `draft-maintenance`：生成 maintenance 草稿容器，汇总 accepted cards 作为语义输入
- 外部 Agent：根据 draft + accepted cards 编辑 canonical PRD / Requirement / decisions
- `apply-maintenance`：只负责 finalize、写 changelog、消费 cards、更新状态；不自动改 canonical PRD 正文

## 导出与收尾

导出 workspace：

```bash
pmagent export --project <project> --workspace <workspace>
```

收尾本轮 workspace：

```bash
pmagent workspace-close --workspace <workspace>
```

若可关闭，会生成：

```text
memory/global-candidates/<date>-<workspace>-global-promotion.md
```

## CLI surface rule

Canonical user-facing entrypoints should stay small:

- State/navigation: `status`, `start`, `resume`, `next`, `review`.
- Phase work: `clarify`, `research`, `prd`, `dev`, `observe`.
- Integration work: `infra`.
- Setup/ops: `init`, `upgrade`, `workspace-init`, `switch`, `skills-sync`.

Legacy aliases and generator-style shortcuts are intentionally unsupported. Do
not put removed spellings in docs, generated suggestions, or automation.

`dev-readiness` is executed from `skills/steps/dev-readiness/skill.md` by an external Agent.
`pmagent dev` only inspects slice artifacts and records run evidence.

## 常用命令

```bash
pmagent init --dir <data_dir>
pmagent upgrade --data-dir <data_dir>
pmagent status
pmagent route
pmagent review
pmagent start
pmagent next
pmagent resume
pmagent workspace-init --project <project> --workspace <workspace>
pmagent switch --list
pmagent switch <project> [workspace]
pmagent switch --clear
pmagent clarify status
pmagent research status
pmagent prd status
pmagent dev slices --workspace <workspace> --json
pmagent dev run-record --workspace <workspace> --slice <slice-id> --command "<command>" --status passed|failed|blocked
pmagent dev lesson-review --workspace <workspace> --json
pmagent observe run --project <project>
pmagent observe audit --workspace <workspace> --run-catch-up
pmagent observe review --workspace <workspace>
pmagent observe maintenance-status --workspace <workspace>
pmagent export --project <project> --workspace <workspace>
pmagent workspace-close --workspace <workspace>
```
