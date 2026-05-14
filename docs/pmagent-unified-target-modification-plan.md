# PMAgent 统一目标修改文档：主流程去 mode 化、研发纵向切分、PM Infra 完整基础设施

日期：2026-05-02

## 1. 文档目的

这份文档把本轮要覆盖的三条修改线合并成一个目标态：

1. 主流程弱化 / 去掉 `mode`，改成以可插拔 skill 为核心的导航协议。
2. 开发侧引入 Dev Readiness Gate 和 vertical slice，把 PRD 转成可执行、可验证的研发切片。
3. `docs/prodtech-agent-pm-infra` 的完整基础设施目标：飞书 Wiki 同步、飞书 Base 卡片中转、GitHub PM Data 全量镜像、军师/元分析、PMA 启动轮询、多用户协作、反馈闭环，以及本轮覆盖后的 OpenClaw 运行时边界。

这不是旧文档的简单拼接，而是按最新口径统一后的修改目标。`prodtech-agent-pm-infra` 的完整内容都要纳入：Requirement、PRD、decisions、research、debate、signal-source audit 和新生成的 OpenClaw 协议。旧文档中“本地军师运行”或“分析 Agent 主要读取飞书文件层”的说法，在本轮被覆盖为：**OpenClaw 读取 GitHub PM Data 镜像；飞书继续作为人可读文件协作层、Base 卡片交付层和反馈层。**

## 2. 已检索依据

主流程去 mode 化：

- `docs/pmagent-three-layer-product-model.md`
- `.omx/context/pmagent-mainflow-redesign-20260428T074837Z.md`
- `.omx/specs/deep-interview-pmagent-mainflow-redesign.md`

研发纵向切分：

- `docs/pmagent-current-feishu-claw-dev-slice-plan.md`
- `docs/pmagent-feishu-file-layer-dev-doc-design.md`
- `docs/pmagent-three-layer-product-model.md`

PM Infra 完整基础设施与 OpenClaw 覆盖：

- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/Requirement.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/prd/2026-04-30-pm-infra-v1-prd.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/workspace-summary.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/context/clarifying-log.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/decisions/*.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/research/*.md`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/context/debates/2026-04-30-agent-openclaw-agent/synthesis.md`
- `.omx/specs/deep-interview-pm-infra-modification.md`
- `.omx/interviews/pm-infra-modification-20260502T083636Z.md`
- `docs/prodtech-agent-pm-infra/config/openclaw-advisor-protocol.md`
- `docs/prodtech-agent-pm-infra/config/candidate-card.schema.json`
- `docs/prodtech-agent-pm-infra/workspaces/prodtech-agent-pm-infra/next-modification-summary.md`

## 3. 一句话目标

PMAgent 要从一个 `mode` 驱动的本地 PM 流程 CLI，改成一个 **面向外部 Agent 的 PM-to-dev 文件协议工具**：

```text
pmagent init 创建 PM Data 目录
  -> 主流程按需调用 skill，而不是被 mode 锁住
  -> PRD 稳定后进入 dev-readiness，生成 dev-plan 和 vertical slices
  -> PM Data 通过飞书 Wiki 做人可读展示，通过 GitHub 做机器全量镜像
  -> OpenClaw 读取 GitHub PM Data 镜像，产出 Candidate Card 到飞书 Base
  -> PMAgent 拉回 inbox，用户 review 后再改本地 canonical 文件
  -> 研发侧 run evidence / lesson candidates 回流主流程
```

## 4. 不变原则

1. PMA / PMAgent 是 PM Data 文件系统的唯一写入入口。
2. 当前 `pmagent` 源码仓库不是 PM Data 仓库；真实联调必须用 `pmagent init --dir <data_dir>` 新建数据目录。
3. PM Data 目录可以作为独立 Git 仓库推送到 GitHub；OpenClaw 读取的是这个 GitHub PM Data 镜像。
4. 飞书 Wiki / Docs 是团队可见的文件协作层，不是 canonical truth。
5. 飞书 Base 是 Candidate Card / Suggestions / Feedback 的结构化中转层，不是本地文件的替代状态机。
6. OpenClaw 不创建、不部署、不触发本地 PMAgent，也不直接修改 PM Data 文件正文。
7. Candidate Card 是建议，不是可执行指令；所有改变 canonical 文件的动作都必须经过本地 inbox / review。
8. 代码权威源仍是 GitHub 代码仓库；PMAgent 只记录 codebase、branch、commit、test command、run evidence 和 lesson candidates。
9. 研发经验的一手候选沉淀由研发侧 Agent 在 slice 执行现场产生；OpenClaw 只做二次分析、聚类、去重和建议。
10. `prodtech-agent-pm-infra` 中的飞书 Wiki、飞书 Base、GitHub、Candidate Card、元分析、反馈闭环、多用户协作都属于本轮基础设施目标，不得只落成 OpenClaw 协议文件。

## 5. 统一架构

```text
外部 Agent / 用户
  Codex / Claude Code / Kiro
        |
        v
pmagent CLI
  创建和操作 PM Data 目录
  维护 skill registry / recommended skills / current-state / inbox
  生成 Requirement / PRD / decisions / dev-plan / slices / run evidence
        |
        | Git push
        v
GitHub PM Data repo
  OpenClaw 可读的完整机器镜像
  包含主流程文件、dev 文件、状态文件、candidate 状态和 observation 记录
        |
        | clone / pull / analyze
        v
OpenClaw 军师
  读取 GitHub PM Data
  产出标准 Candidate Card
        |
        | write rows
        v
飞书 Base
  Cards / Suggestions / Feedback
        |
        | pull inbox / write review feedback
        v
pmagent inbox / review
  accept / reject / snooze / defer
  需要时调用主流程 skill 或 dev skill 修改本地文件

飞书 Wiki / Docs
  团队可见的 PM / dev 文件镜像
  可评论、可分享、可归档
  不反向覆盖本地 canonical 文件
```

## 6. 修改线 A：主流程弱化 mode

### 6.1 目标

主流程不再由 `mode` 决定下一步。`mode` 最多保留为旧版 preset / bundle，不再是运行时核心状态。

旧体验：

```text
你现在处于 zero-to-one mode，所以必须进入 research。
```

新体验：

```text
当前需求澄清度较高。
推荐 skill：research / write-prd / debate。
这些都是建议，用户可以选择任意 skill。
```

### 6.2 新概念

| 概念 | 新定位 |
|---|---|
| `mode` | 不再作为主流程核心；旧 workspace 可兼容读取，但不驱动流程 |
| `phase` | 生命周期 / 状态维度，保留展示和统计价值，不做硬流程锁 |
| `readiness` | 导航信号，不是 gate lock |
| `recommended_next_step` | 软推荐，不自动跳转 |
| `skill` | 主流程核心执行单元 |
| `async skill` | 用户主动调用的旁路任务，例如 research / debate / observation |
| `inbox` | 远端建议、开发反馈、军师卡片、经验候选的统一待审入口 |

### 6.3 Skill 合同

每个 skill 应像小型工作协议，而不是只是一段 prompt：

```text
Skill
  - 解决什么问题
  - 读取哪些上下文
  - 产出什么 artifact
  - 是否修改 canonical 文件
  - 是否可异步运行
  - 如何呈现结果
  - 推荐哪些下一步
  - 用户如何采纳 / 忽略结果
```

### 6.4 需要改的代码面

直接触点：

- `src/pmagent/scaffold/config/agent-workflow.yaml`
- `src/pmagent/current_state.py`
- `src/pmagent/cli_routing.py`
- `src/pmagent/presentation.py`
- `src/pmagent/scaffold/AGENTS.md`
- `src/pmagent/scaffold/CLAUDE.md`
- `src/pmagent/templates/WORKSPACE_SUMMARY_TEMPLATE.md`
- `src/pmagent/skills/README.md`
- `src/pmagent/skills/modes/*`
- `src/pmagent/skills/steps/*`

预期改法：

1. 从状态模型中移除运行时必需的 `mode` 依赖。
2. 增加 `skill_registry` / `available_skills` / `recommended_skills` / `active_skill`。
3. `status` / `next` / `resume` 不再输出“当前 mode 决定路径”，而是输出当前 artifact、readiness、inbox、recommended skills。
4. `route_mode` / `mode_skill_path` 一类测试改成保护 skill contract / recommendation / inbox 行为。
5. `skills/modes` 中的内容要迁移成 skill bundle 或 legacy preset，不再作为主入口。
6. Debate / observation / research 明确作为 async skill 或 side-channel，不切换主流程 mode。

## 7. 修改线 B：开发侧 vertical slice

### 7.1 目标

PRD 不直接交给开发。PRD 稳定后先进入 Dev Readiness Gate，再生成 `dev/dev-plan.md` 和 `dev/slices/*.md`。

```text
prd/current.md
  -> dev-readiness
  -> dev/dev-plan.md
  -> dev/slices/SL-001.md
  -> dev/runs/SL-001/run-*/
  -> dev/qa/
  -> dev/lessons/
```

### 7.2 Dev Readiness Gate 职责

Dev Readiness Gate 不替代 PRD，它负责把 PRD 转译成工程可执行包：

- implementation decisions；
- testing decisions；
- out of scope；
- domain language；
- module risks；
- vertical slices；
- first AFK slice；
- HITL / AFK 标记；
- public behavior tests；
- ready-for-dev checklist。

### 7.3 dev-plan

`dev/dev-plan.md` 至少包含：

- PRD 链接；
- 产品目标；
- 工程边界；
- 不做什么；
- 领域语言；
- 关键模块和风险；
- 数据 / API / UI / 权限判断；
- 测试策略；
- slice 拆分顺序；
- first AFK slice；
- 需要人工判断的事项。

### 7.4 Slice 契约

每个 slice 必须是用户可观察、可交付、可验证的垂直增量，而不是数据库 / API / 前端的水平拆分。

`dev/slices/SL-001.md` 模板：

```markdown
# Slice SL-001: <标题>

## Goal

## User Story

## Product Context

- PRD:
- Requirement:
- Decisions:

## What To Build

## Acceptance Criteria

## Public Behavior Tests

## Codebase

- codebase_id:
- base_commit:
- branch:
- worktree_path:

## Owned Paths

## Shared Paths

## Commands

## Out Of Scope

## Handoff Notes
```

### 7.5 Codebase registry

PMAgent 不复制代码库，只登记代码库：

```text
dev/codebases.json
```

字段至少包含：

- `id`
- `github_url`
- `local_root`
- `vcs`
- `base_branch`
- `test_commands`
- `agent_instructions`

### 7.6 Worktree per slice

并行研发时推荐：

```text
一个 slice 一个 git worktree
一个 slice 一个 branch
```

规则：

1. `owned_paths` 是该 slice 的主要修改范围。
2. `shared_paths` 必须显式声明。
3. 未声明的共享文件不能随意改。
4. 跨 slice 冲突进入 inbox。
5. 合并通过 Git / PR / review 完成。

### 7.7 Run evidence 与 lesson candidates

每次 slice 执行生成：

```text
dev/runs/SL-001/run-YYYYMMDD-NNN/
  run.json
  touched-files.json
  commands.jsonl
  test-results.json
  decisions.md
  blockers.md
  diff-summary.md
  lesson-candidates.jsonl
```

研发侧 Agent 必须在现场提取候选经验，但候选经验不能自动晋升：

```text
lesson_candidate
  -> inbox
  -> accept / ignore / defer
  -> accepted_lessons / rejected_lessons
```

OpenClaw 可以读取 run evidence 和 lesson candidates 做二次复盘，但不能直接把候选经验写成永久规则。

## 8. 修改线 C：prodtech-agent-pm-infra 完整基础设施

### 8.1 范围纠正

这一条线不是“OpenClaw 对接协议”单点。`docs/prodtech-agent-pm-infra` 是一个完整 PM Data 目录，里面已经沉淀了基础设施升级的完整需求、PRD、决策和研究。

必须纳入的完整内容包括：

1. 飞书 Wiki 同步层。
2. 飞书 Base 卡片中转层。
3. GitHub PM Data 全量镜像。
4. 军师 / 元分析层。
5. PMA 启动轮询与本地 candidate review。
6. Candidate Card 通用建议协议。
7. 多用户、对等、松耦合协作模型。
8. 反馈闭环与 advisor policy。
9. 信号源矩阵审计。
10. OpenClaw 作为本轮覆盖后的外部军师运行时。

### 8.2 PM Infra 的原始目标

`Requirement.md` 的核心目标是：

```text
为 PM Agent 构建集中化基础设施层：
  本地 Git = 全量版本源
  飞书 Wiki = 协作 / 展示 / 流转层
  飞书 Base = 卡片中转层
  GitHub = 机器全量镜像
  军师 = 元分析层
  目标 = 多项目全局视图 + 跨用户协作 + 人/Agent 双向进化
```

这条线要把 PMAgent 从“单项目本地推进工具”扩展为“多项目、可协作、可被元分析的基础设施层”。

### 8.3 飞书 Wiki 同步层

目标：把本地 PM Data 中的人可读 Markdown 增量同步到飞书 Wiki / Docs，形成团队可见、可评论、可分享的协作展示层。

同步范围：

| 推送到飞书 Wiki | 不推送到飞书 Wiki |
|---|---|
| `Requirement.md` | `.pmagent/*.json` |
| `workspace-summary.md` | `observations/` 运行日志 |
| `research/*.md` | `candidate-updates/` 中间产物 |
| `decisions/*.md` | Git commit 历史 |
| `prd/*.md` | 机器状态和缓存 |
| `strategy/*.md` | 原始敏感运行数据 |
| `context/clarifying-log.md` | |
| `exports/` | |

规则：

1. 一个 Project 对应一个 Wiki 空间。
2. Workspace 是 Wiki 空间下的子节点。
3. 飞书正文默认只读，评论和标注可以产生反馈。
4. PMA / PMAgent 是唯一正文写入入口。
5. 飞书侧正文变化不能反向覆盖本地文件，只能进入 conflict / inbox。
6. 同步触发包括 session 结束、phase / 关键 artifact 落盘、手动 sync。

### 8.4 飞书 Base 卡片中转层

目标：所有信号源统一标准化为 Candidate Card，写入飞书 Base；PMAgent 启动时拉取 `status=inbox` 的卡片，用户 review 后状态回写。

物理存储粒度：

```text
Project = Wiki Space = Cards Base
Workspace = Cards Base 中的 target_workspace 路由字段
```

这个边界不能混淆：Base 表按 Project 分表，卡片语义按 workspace 路由。

Base 字段映射：

| Base 字段 | Candidate Card 字段 |
|---|---|
| `card_id` | `card_id` |
| `source_type` | `source_type` |
| `source_ref` | `source_ref` |
| `target_workspace` | `target.workspace` |
| `title` | `suggestion.title` |
| `body` | `suggestion.body` |
| `evidence` | `suggestion.evidence` |
| `suggested_action` | `suggestion.suggested_action` |
| `urgency` | `suggestion.urgency` |
| `status` | `lifecycle.status` |
| `created_at` | `lifecycle.created_at` |
| `reviewed_at` | `lifecycle.reviewed_at` |
| `review_note` | `lifecycle.review_note` |
| `expires_at` | `lifecycle.expires_at` |

状态流：

```text
OpenClaw / 分析层
  -> 产出标准化 Candidate Card
  -> 写入飞书 Base(status=inbox)

PMAgent 启动 / 手动 pull
  -> 查询 Cards Base(status=inbox, target_workspace=current)
  -> 写入本地 candidate-updates/
  -> 复用 observe audit / review 体验
  -> accept / reject / snooze
  -> 回写 Base status + reviewed_at + review_note
```

### 8.5 Candidate Card 通用建议协议

Candidate Card 从 observation 专用队列扩展为所有建议的统一通道。

`source_type` 统一为：

- `external_observation`
- `behavior_analysis`
- `cross_project`
- `efficiency`
- `consistency`

Candidate Card 必须包含：

- `card_id`
- `source_type`
- `source_ref`
- `target.project`
- `target.workspace`
- `suggestion.title`
- `suggestion.body`
- `suggestion.evidence`
- `suggestion.suggested_action`
- `suggestion.urgency`
- `lifecycle.status`
- `lifecycle.created_at`
- `lifecycle.reviewed_at`
- `lifecycle.review_note`
- `lifecycle.expires_at`

协议原则：

1. 卡片只表达建议，不嵌入自动执行指令。
2. MCP 不作为卡片协议；MCP 是 client-pull，卡片需要 server-push + 人工审批 + 生命周期管理。
3. PMA 不直接处理飞书评论/讨论原始数据，分析层先标准化为卡片。
4. 所有卡片都必须有 evidence。

### 8.6 GitHub PM Data 全量镜像

目标：PM Data 全量 push 到 GitHub，作为机器可读全量镜像。

GitHub 与飞书 Wiki 的区别：

| 层 | 受众 | 范围 | 作用 |
|---|---|---|---|
| 飞书 Wiki / Docs | 人 | 人可读 Markdown 白名单 | 展示、协作、评论、标注 |
| GitHub PM Data repo | 机器 / OpenClaw | 全量 PM Data，包括 `.pmagent`、observations、candidate 状态 | 分析读取、版本历史、恢复 |

注意：

1. PM Data repo 与 `pmagent` 源码 repo 必须分离。
2. GitHub PM Data repo 需要敏感信息排除策略。
3. 如果开放 Wiki 空间给别人，应同步评估 GitHub PM Data repo 的 read 权限。
4. OpenClaw 读取 GitHub PM Data repo，而不是读取当前源码仓库。

### 8.7 军师 / 元分析层

原始 PM Infra 文档定义的军师目标：

- 分析对象不是项目内容好坏，而是人 + Agent 的协作机制；
- 关注推进效率、行为模式、认知短板、跨项目复用、文档一致性；
- 产出统一为 Candidate Card；
- 不自动改 Agent 行为、不自动修改 workflow / skill / mode 配置；
- 人是校准桥梁。

信号源优先级：

| 优先级 | source_type | 价值定位 | 对本地 / Git 依赖 |
|---|---|---|---|
| P0 | `behavior_analysis` | 分析人的行为模式、提问质量、决策模式 | 高 |
| P0 | `efficiency` | 检测 phase 停留、活跃度、推进卡点 | 极高 |
| P1 | `cross_project` | 跨项目知识复用和模式识别 | 低到中 |
| P1 | `consistency` | Requirement / PRD / decisions / summary 一致性兜底 | 低 |
| P2 | `external_observation` | 复用已有 observation finding | 中 |

信号源矩阵的关键结论：

1. `behavior_analysis` 和 `efficiency` 的核心数据依赖 `.pmagent/current-state.json`、Git diff、审批行为、phase 时间戳和 commit 时间线。
2. 这些核心数据不在飞书 Wiki，必须通过本地 Git / GitHub PM Data 镜像提供。
3. `consistency` 基本可从人可读文档完成，是最适合飞书侧读取的信号源。
4. `cross_project` 和 `external_observation` 可以部分依赖飞书，但完整质量仍依赖 Git / policy / history。

### 8.8 OpenClaw 覆盖决策

原 `prodtech-agent-pm-infra` 文档接受的是“军师本地运行 + GitHub 全量同步”。本轮用户明确覆盖：

- OpenClaw 是第一版军师运行时；
- OpenClaw 拉 GitHub PM Data repo；
- OpenClaw 外部完成分析；
- OpenClaw 把 Candidate Card 写入 Project Cards Base；
- PMAgent 拉取卡片、用户 review，并把反馈写回 Base 供下一轮校准。

因此最终口径是：

```text
原文档完整基础设施目标保留
  + 军师运行位置由“本地脚本”覆盖为“外部 OpenClaw”
  + 数据输入仍是 GitHub PM Data 镜像
  + 输出仍是 Feishu Base Candidate Card
  + PMAgent 仍是 PM Data 文件系统唯一写入入口
```

PMAgent 不负责：

- 创建 OpenClaw；
- 部署 OpenClaw；
- 触发 OpenClaw；
- 让 OpenClaw 直接写 PM Data 文件；
- 把 OpenClaw 输出当作可自动执行指令。

当前已有协议产物：

```text
docs/prodtech-agent-pm-infra/config/openclaw-advisor-protocol.md
docs/prodtech-agent-pm-infra/config/candidate-card.schema.json
```

源码侧已有协议入口：

```text
pmagent infra protocol
```

### 8.9 PMA 启动轮询与反馈闭环

PMAgent 启动或用户手动拉取时：

1. 查当前 Project 的 Cards Base。
2. 筛选 `status=inbox` 且 `target_workspace=current_workspace`。
3. 写入本地 `candidate-updates/` 或统一 inbox。
4. 复用 candidate review / observe audit 体验。
5. review 后写回 Base。
6. 按 source_type 统计 accept / reject / snooze。
7. 写入 advisor policy / feedback，供 OpenClaw 下一轮分析校准。

反馈规则方向：

- reject + review_note：降低类似建议权重；
- 连续 accept：提升对应 source_type / pattern 的频率；
- snooze 长期未处理：降低 urgency；
- expired：避免建议长期污染 inbox。

### 8.10 多用户协作模型

用户模型是多租户、对等、松耦合：

1. 每个人有自己的 PM Data 主权。
2. 可以选择性开放 Wiki 空间。
3. 不存在主从关系或强审批链。
4. CLI/API 权限应与飞书系统权限一致。
5. Agent 能读取什么，取决于用户在飞书 / GitHub 上拥有什么权限。

### 8.11 PM Infra 需要覆盖的 POC / 风险

必须纳入后续实现和验证：

1. Markdown 到飞书文档的格式保真度。
2. 长对话日志的飞书单文档大小限制。
3. 飞书 Base 字段映射 Candidate Card Schema 的端到端 POC。
4. 飞书卡片模板 / Button callback 能力。
5. GitHub PM Data repo 的敏感信息边界。
6. 飞书 API 失败时本地主流程不阻塞。
7. GitHub 不可用时 OpenClaw 可延后，PMAgent 本地仍可运行。
8. 飞书正文人工改动不反向覆盖本地，而是进入 conflict / inbox。

## 9. PM Data 与源码仓库边界

必须严格区分：

```text
C:\Users\20663\Desktop\pmagent\pmagent
  -> pmagent 源码仓库
  -> 用于开发 CLI 工具
  -> 不能作为 OpenClaw 读取的 PM Data 仓库

<new-data-dir>
  -> pmagent init 创建
  -> PM Data 目录
  -> 可作为独立 Git 仓库
  -> 推送到 GitHub 后供 OpenClaw clone/pull
```

真实联调流程必须是：

```text
pmagent init --dir <test-pm-data-dir>
  -> 在 <test-pm-data-dir> 中创建项目 / workspace / PRD / dev slice
  -> 将 <test-pm-data-dir> 初始化为独立 Git repo
  -> 推送到 GitHub PM Data repo
  -> OpenClaw 拉 GitHub PM Data repo
  -> OpenClaw 写 Feishu Base Cards
  -> pmagent 从 Base 拉 inbox
```

## 10. 统一文件布局目标

PM Data 目录目标结构：

```text
<pm-data>/
  config/
    projects.json
    integrations.json
    openclaw-advisor-protocol.md
    candidate-card.schema.json
  projects/
    <project>/
      PROJECT.md
  workspaces/
    <workspace>/
      Requirement.md
      workspace-summary.md
      prd/
        current.md
      decisions/
      research/
      context/
      inbox/
      candidate-updates/
      dev/
        dev-plan.md
        codebases.json
        slices/
          SL-001.md
        runs/
          SL-001/
            run-YYYYMMDD-NNN/
        qa/
        lessons/
          lesson-candidates.jsonl
          accepted-lessons.md
      .pmagent/
        current-state.json
```

## 11. CLI / 协议面目标

### 11.1 主流程 skill 面

需要新增或重构的能力：

- 列出可用 skill；
- 展示推荐 skill；
- 运行单个 skill；
- 支持 async skill run；
- 把 async result 进入 inbox 或 artifact；
- `status` / `next` / `resume` 展示推荐而非 mode 路径。

可能命令形态：

```text
pmagent skills
pmagent skill run <skill>
pmagent skill status <run-id>
pmagent next
pmagent review
```

命令名可以按现有代码风格最终定，但语义必须脱离 `mode`。

### 11.2 Dev readiness / slice 面

需要新增：

```text
skills/steps/dev-readiness/skill.md   # 外部 Agent 执行
pmagent dev slices
pmagent dev run-record
pmagent dev lesson-review
```

第一目标不是“自动写代码”，也不是让 CLI 语义拆分需求；外部 Agent 根据 `dev-readiness` skill 生成和维护研发协议文件：

- `dev/dev-plan.md`
- `dev/slices/*.md`
- `dev/codebases.json`
- `dev/runs/**`
- `dev/lessons/**`

### 11.3 PM Infra 协议面

当前已有：

```text
pmagent infra protocol
```

后续协议面不只服务 OpenClaw，而是要覆盖完整 PM Infra：

- 生成 OpenClaw 读取 GitHub PM Data、写入 Feishu Base 的协议；
- 生成 Candidate Card schema；
- 输出 PM Data / GitHub / Feishu Wiki / Feishu Base 字段约定；
- 描述 Feishu Wiki 白名单同步范围；
- 描述 Feishu Base Cards 表字段和生命周期；
- 描述 PMAgent inbox pull / review / feedback 回写协议；
- 描述 GitHub PM Data 全量镜像边界和敏感信息排除规则；
- 不运行 OpenClaw，不替代 Feishu adapter，不直接做真实外部写入。

后续命令可以拆成更清晰的协议生成面：

```text
pmagent infra protocol
pmagent infra wiki-plan
pmagent infra card-schema
pmagent infra github-plan
pmagent infra protocol
```

命令名可以调整，但能力边界必须覆盖 `prodtech-agent-pm-infra` 的完整基础设施，而不是只生成 advisor protocol。

## 12. 飞书与 GitHub 联调环境变量

真实外部联调前必须停止并要求用户填写环境变量。候选变量：

```text
PMAGENT_DATA_DIR=<new-pm-data-dir>
PMAGENT_GITHUB_REMOTE=<github-pm-data-repo-url>
PMAGENT_GIT_USER_NAME=<optional-git-user-name>
PMAGENT_GIT_USER_EMAIL=<optional-git-user-email>

PMAGENT_FEISHU_APP_ID=<feishu-app-id>
PMAGENT_FEISHU_APP_SECRET=<feishu-app-secret>
PMAGENT_FEISHU_BASE_APP_TOKEN=<project-cards-base-app-token>
PMAGENT_FEISHU_CARDS_TABLE_ID=<candidate-cards-table-id>
PMAGENT_FEISHU_WIKI_SPACE_ID=my_library
PMAGENT_FEISHU_WIKI_PUSH_COMMAND=<optional-custom-adapter-command>
```

默认 Feishu Wiki 路径应在检测到可用且已配置的 `lark-cli` 时使用内置 `python -m pmagent.ops.lark_wiki_push` adapter；只有需要自定义空间、转换器或推送策略时才要求额外 command。变量名可以继续收敛，但必须仍满足：

- 凭证不写入仓库；
- `.env` 不推送；
- 日志不输出 secret；
- 内置 adapter 复用 `workspaces/<workspace>/.pmagent/feishu-wiki-nodes.jsonl` 中已有的文件到 Wiki node 映射；
- 真实写入前打印将要操作的 PM Data 目录、GitHub remote、飞书 Base 表和 Wiki 空间。

## 13. 实施顺序

这里的顺序是依赖顺序，不是降级目标。

### Step 1：统一 PM Data 与 Infra 协议骨架

1. 固化 PM Data 目录边界。
2. 固化 `config/integrations.json`。
3. 固化 Feishu Wiki 同步白名单和 conflict / inbox 规则。
4. 固化 Feishu Base Candidate Card 字段映射和生命周期。
5. 固化 GitHub PM Data 全量镜像规则。
6. 固化 `openclaw-advisor-protocol.md` 和 `candidate-card.schema.json`。
7. 固化 `inbox` / `candidate-updates` / `dev` 文件布局。

### Step 2：主流程去 mode 化

1. 引入 skill registry。
2. 将 `mode` 从 runtime routing 中移除。
3. 将 `phase/readiness/recommended_next_step` 改为导航信号。
4. 将 `status/next/resume/review` 调整为 skill 推荐和 inbox 展示。
5. 修改 scaffold AGENTS / CLAUDE / templates。
6. 重写 mode-era 测试。

### Step 3：Dev Readiness 与 slices

1. 增加 `dev/dev-plan.md` 模板。
2. 增加 `dev/slices/*.md` 模板。
3. 增加 `dev/codebases.json`。
4. 增加 slice metadata 和 run evidence。
5. 增加 lesson candidates review。

### Step 4：Feishu Wiki 文件协作层

1. 只同步人可读 Markdown 白名单。
2. Project 映射 Wiki space，Workspace 映射 Wiki 子节点。
3. 支持 session 结束、关键 artifact 落盘、手动 sync 三类触发。
4. Feishu 侧正文变化不反向覆盖本地文件，只进入 conflict / inbox。
5. 验证 Markdown 保真度、长文档限制、权限和失败重试。

### Step 5：Feishu Base 卡片中转层

1. 建立 Project 级 Cards Base。
2. 使用 `target_workspace` 做 workspace 路由。
3. Base 字段映射 Candidate Card schema。
4. PMAgent 拉取 `status=inbox` 的卡片。
5. 本地 review 后写回 `status` / `reviewed_at` / `review_note`。

### Step 6：GitHub PM Data 镜像

1. 新 PM Data 目录初始化为独立 Git repo。
2. 默认排除 secrets / transient cache。
3. 推送完整 PM Data 到 GitHub remote。
4. 确认 OpenClaw 读取的是 PM Data repo，不是 `pmagent` 源码 repo。

### Step 7：OpenClaw 联调

1. 用户填写环境变量。
2. 用新建 PM Data 目录跑真实 E2E。
3. OpenClaw 拉 GitHub PM Data。
4. OpenClaw 生成 Candidate Card 到飞书 Base。
5. PMAgent 拉回 inbox。
6. 本地 review 后回写 Base。
7. 下一轮 OpenClaw 能读取反馈统计并调整建议策略。

## 14. 验收标准

主流程：

1. `status/next/resume` 不再依赖 `mode` 决定唯一下一步。
2. 用户可以看到多个 recommended skills。
3. readiness 只做导航，不阻止用户跳过 skill。
4. Debate / observation / research 能作为 async skill 或 side-channel 回流。
5. 旧 workspace 中的 `mode` 字段不会破坏读取，但不再驱动主流程。

研发侧：

1. PRD 可生成 `dev/dev-plan.md`。
2. dev-plan 可生成至少一个 `dev/slices/SL-001.md`。
3. slice 记录 codebase、base commit、branch、owned/shared paths、commands。
4. slice run 生成 run evidence。
5. lesson candidates 进入 inbox，经 review 后才晋升。
6. 开发反馈能回流 Requirement / PRD / decision / dev-plan，而不是在代码侧硬补。

PM Infra / Feishu / GitHub / OpenClaw：

1. Feishu Wiki 同步只推送人可读 Markdown 白名单。
2. Feishu Wiki / Docs 不作为 canonical source，人工正文改动进入 conflict / inbox。
3. Feishu Base 使用 Project 级 Cards 表，workspace 通过 `target_workspace` 路由。
4. Candidate Card schema 可约束 Feishu Base 字段。
5. Base card 必须带 evidence 和 target workspace。
6. PMAgent 能拉取 `status=inbox` 卡片并写入本地 inbox / candidate-updates。
7. PMAgent review 能写回 feedback。
8. GitHub PM Data repo 与 `pmagent` 源码 repo 边界清晰。
9. GitHub PM Data 镜像包含机器分析需要的全量 PM Data，同时排除 secrets。
10. `pmagent infra protocol` 能生成 OpenClaw 协议和 schema。
11. OpenClaw 读取 GitHub PM Data，而不是读取当前源码仓库或只读 Feishu 文档层。
12. OpenClaw 不直接写 PM Data 文件。
13. 真实联调使用新建 PM Data 目录，不使用当前源码仓库。
14. 反馈统计能进入 advisor policy / feedback，供下一轮分析校准。

## 15. 明确不做

1. 不把飞书 Base 做成完整看板系统。
2. 不把飞书 Wiki / Docs 当 canonical source。
3. 不让 OpenClaw 或飞书反向覆盖本地 Markdown 正文。
4. 不让分析 Agent 自动修改 workflow / skill / agent 行为。
5. 不把研发侧 lesson candidate 自动晋升为永久经验。
6. 不把代码复制进 PM Data 或飞书；代码权威仍是 GitHub。
7. 不在没有用户环境变量和确认的情况下做真实 Feishu / GitHub 写入。
8. 不把本轮范围缩窄成 OpenClaw 对接协议；`prodtech-agent-pm-infra` 的 Wiki、Base、GitHub、PMA polling、反馈闭环和多用户协作都要纳入。

## 16. 当前需要特别注意的文档冲突

1. `docs/pmagent-three-layer-product-model.md` 和早期 `.omx/context/pmagent-mainflow-redesign-*` 曾提到 server / kanban；当前应按更新后的文件层方案理解，不做 V1 自建看板。
2. `docs/pmagent-current-feishu-claw-dev-slice-plan.md` 曾写“分析 Agent 读取飞书文件层”；本轮 OpenClaw 决策覆盖为“OpenClaw 读取 GitHub PM Data 镜像”，飞书仍用于文件展示和卡片交付。
3. `docs/prodtech-agent-pm-infra` 原文档曾接受本地军师运行；用户已明确覆盖为外部 OpenClaw。
4. `mode` 不是完全不能出现在兼容层或旧文档里，但不得继续作为主流程 runtime 的核心驱动。
5. `prodtech-agent-pm-infra` 原文档不是只在讨论 OpenClaw；它还定义了 Feishu Wiki、Feishu Base、GitHub PM Data、Candidate Card、PMA startup polling、多用户协作和反馈策略，这些都要保留为目标范围。

## 17. 总结

这轮真正要覆盖的是一个统一转向：

```text
从：mode 驱动的 PM 文档流程
到：skill 驱动的 PM-to-dev 协议工具

从：PRD 直接交给开发
到：Dev Readiness Gate + vertical slice + run evidence + lesson review

从：本地军师 / 飞书文件层分析
到：OpenClaw 拉 GitHub PM Data，写 Feishu Base Candidate Card，本地 inbox review

从：只补一个 advisor protocol
到：覆盖 prodtech-agent-pm-infra 的完整基础设施：Feishu Wiki、Feishu Base、GitHub PM Data、OpenClaw、PMA polling、feedback policy、多用户协作
```

最终目标不是新增一个孤立功能，而是让 PMAgent 同时具备：

- 可自由选择的主流程 skill；
- 可追踪的 PM Data / GitHub / Feishu Wiki / Feishu Base 协议边界；
- 可执行的开发侧 vertical slice；
- 可审计的 OpenClaw / Candidate Card / feedback 建议闭环；
- 可回流的研发经验和主流程修正机制。
