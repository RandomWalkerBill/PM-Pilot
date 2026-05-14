# PM Agent 项目深度说明（用于项目复盘、对外沟通与简历撰写）

> 文档生成时间：2026-04-25  
> 代码仓库：`pmagent`  
> 包名 / CLI：`pmagent`  
> 当前定位：面向 Claude Code / Codex / Kiro 等外部 Agent 的 CLI-first 产品管理工作流与长期项目记忆系统。

---

## 1. 一句话概括

`pmagent` 是一个用 Python 实现的 **面向外部 AI Agent 的产品管理运行时（PM Agent Runtime）**。它不是传统意义上的 PM SaaS，也不是单纯的文档模板库，而是把 **需求澄清、调研、PRD、外部信号观察、候选变更评审、维护闭环、争议辩论、状态恢复、交付导出** 统一沉淀到一个可恢复、可审计、可由 Agent 调用的本地文件协议和 CLI 工作流中。

更工程化地说：

> 这是一个“Agent 操作系统里的产品管理层”：外部 Agent 负责阅读、推理和写作，`pmagent` 负责提供稳定入口、状态机、文件边界、调度、执行器适配、质量门禁和长期记忆。

---

## 2. 项目要解决的问题

在 Claude Code、Codex、Kiro 这类外部编码 / 产品 Agent 中做长期项目时，常见问题是：

1. **上下文断裂**  
   一次会话结束后，Agent 不知道当前项目到哪一步了，也不知道哪些结论已经稳定、哪些还只是草稿。

2. **文档与状态混在一起**  
   `Requirement.md`、`PRD.md`、聊天记录、调研记录经常相互污染：Agent 可能把临时想法写进 canonical 文档，也可能把状态摘要当成需求真相。

3. **没有明确工作流前门**  
   用户每次都要告诉 Agent：“现在该干嘛”。缺少类似 `status / next / review / resume` 的统一入口。

4. **外部信息变化无法进入 PM 闭环**  
   竞品、市场、用户反馈、技术生态会变化，但普通文档系统不会持续观察；即使观察到了，也很容易直接污染 PRD，而不是先经过人类 review。

5. **复杂决策缺少结构化反方视角**  
   产品决策常常需要 pro/con、多 Agent 辩论、综合结论，但如果只靠聊天，很难落盘、复审和追踪。

6. **跨平台和执行器差异非常现实**  
   Windows、WSL、macOS、Linux 上 Claude / Codex / Kiro CLI 行为、超时、shell、路径和权限都不一样，直接让 Agent 调工具很容易不稳定。

`pmagent` 的目标就是把这些问题变成一套清晰的本地协议和命令体系。

---

## 3. 核心价值

### 3.1 对用户

- 让外部 Agent 围绕一个长期项目持续工作，而不是每次从零解释。
- 每个 workspace 都有明确的当前状态、当前 phase、下一步建议和 review surface。
- Agent 不再随意改 canonical 文档，而是通过受控路径推进：先生成候选，再 review，再维护。
- 外部信号不会直接改 PRD，而是进入 observation 队列，经过 accept/reject/snooze。
- 复杂争议可以进入 debate 工作流，生成轮次论证和 synthesis，再由用户 review/resolve。
- 本地文件即数据库，适合个人工作流、CLI、Git、Agent、人工复查。

### 3.2 对 Agent

- Agent 不需要猜当前项目状态；运行 `pmagent status` / `pmagent review` 即可知道下一步。
- Agent 有明确写入边界：哪些文件可写，哪些文件不能直接改。
- 工作流状态既有人类可读的 `workspace-summary.md`，也有机器可读的 `.pmagent/current-state.json`。
- hooks 可以在 Agent 会话启动、写文件、执行命令、回复前后注入上下文或做安全校验。

### 3.3 对工程实现

- CLI-first：所有能力都可脚本化、测试、复现。
- Markdown-first：核心 artifact 人类可读、可 Git diff、可审计。
- JSON state：机器可读、易被 CLI 与 hooks 消费。
- Executor abstraction：Claude / Codex / Kiro 执行差异被封装。
- Cross-platform scheduling：Windows Task Scheduler、macOS launchd、Linux systemd user timer。

---

## 4. 技术栈与基础信息

| 类别 | 技术 |
| --- | --- |
| 语言 | Python 3.10+ |
| 包管理 / 构建 | setuptools / `pyproject.toml` |
| CLI 入口 | `pmagent = pmagent.cli:main` |
| 文档格式 | Markdown |
| 状态格式 | JSON / YAML |
| 检索 | BM25、jieba、sqlite-vec、OpenAI embeddings |
| Web 搜索 | Brave Search 相关封装 |
| Agent CLI | Claude、Codex、Kiro CLI |
| 调度 | Windows Task Scheduler、launchd、systemd user timer |
| 测试 | pytest |

`pyproject.toml` 定义：

- package name：`pmagent`
- version：`0.1.0`
- requires-python：`>=3.10`
- dependencies：
  - `openai>=1.0.0`
  - `jieba>=0.42`
  - `rank-bm25>=0.2`
  - `sqlite-vec>=0.1`
  - `PyYAML>=6.0`

当前全量测试状态：

```text
173 passed
```

---

## 5. 核心概念模型

### 5.1 Project 与 Workspace 双层模型

`pmagent` 的核心抽象是 **project / workspace 双层模型**。

#### Project：长期项目层

Project 代表一个长期产品、业务方向或系统。它用于保存跨多个需求周期都有效的知识：

```text
projects/<project>/
  strategy/
  decisions/
  memory/
  background/
  .pmagent/project-state.json
```

Project 层适合存：

- 长期战略
- 长期决策
- 项目记忆
- 背景资料
- observation policy / state 的归属关系

#### Workspace：单次需求 / 一轮工作层

Workspace 代表某一次具体需求、某个产品切片或某轮工作闭环：

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

Workspace 层适合存：

- 当前需求
- 当前上下文
- 澄清记录
- 调研记录
- PRD
- 候选 observation updates
- maintenance draft
- debate artifacts
- 导出交付包

### 5.2 为什么要双层？

这个设计解决了一个关键问题：

> 长期项目知识和一次具体需求的工作状态不能混在一起。

例如：

- “我们长期面向 SMB 用户”是 project knowledge。
- “本轮要做 onboarding 改版”是 workspace scope。
- “竞品今天发布了新功能”是 project-level observation。
- “这个信号对当前 onboarding workspace 有影响”则变成 workspace-level candidate update。

---

## 6. 总体架构

### 6.1 总体分层

```text
┌────────────────────────────────────────────────────────────┐
│                    外部 Agent / 用户                       │
│        Claude Code / Codex / Kiro / Human Operator          │
└────────────────────────────┬───────────────────────────────┘
                             │ CLI / hooks / files
┌────────────────────────────▼───────────────────────────────┐
│                     pmagent CLI 前门                       │
│ status / route / review / start / next / resume / observe  │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                    工作流与状态路由层                       │
│ cli_routing / cli_phases / current_state / readiness        │
└───────────────┬──────────────────────┬────────────────────┘
                │                      │
┌───────────────▼─────────────┐ ┌──────▼─────────────────────┐
│ Observation 外部信号闭环    │ │ Debate 多视角辩论闭环       │
│ observe plan/run/ingest     │ │ defender/attacker/synth    │
│ candidate review/maintenance│ │ round artifacts/synthesis  │
└───────────────┬─────────────┘ └──────┬─────────────────────┘
                │                      │
┌───────────────▼──────────────────────▼────────────────────┐
│                     本地文件协议层                         │
│ Markdown artifacts + JSON machine state + YAML config      │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│                  执行器与平台适配层                         │
│ Claude / Codex / Kiro / subprocess / scheduler / hooks      │
└────────────────────────────────────────────────────────────┘
```

### 6.2 设计原则

1. **CLI 是第一接口**：外部 Agent 通过稳定 CLI 进入系统。
2. **状态可恢复**：每个 workspace 都有 `workspace-summary.md` 和 `.pmagent/current-state.json`。
3. **文档边界清晰**：Requirement / PRD 是 canonical artifact；日志、summary、candidate card 不能随意覆盖 canonical 文档。
4. **外部信号先 review 后维护**：observation 不直接修改 PRD，只产生 candidate update。
5. **Debate 是 side-channel**：debate 不直接改变 canonical 结论，只生成 synthesis，等待 review/resolve。
6. **Agent 写入受约束**：hooks、prompt、executor protocol 都限制 Agent 的直接写入路径。
7. **跨平台优先**：Windows 是一等目标，而不是只在 WSL/macOS 上成立。

---

## 7. 仓库文件结构

### 7.1 顶层结构

```text
pmagent/
  pyproject.toml
  README.md
  docs/
  src/
    pmagent/
  tests/
```

### 7.2 `src/pmagent` 结构总览

```text
src/pmagent/
  cli.py                    # 顶层 CLI parser 与主入口
  cli_helpers.py            # CLI 辅助、分发、workspace context 解析
  cli_routing.py            # status/route/review/start/next/resume 路由
  cli_phases.py             # clarify/research/prd phase 命令
  cli_workspace.py          # workspace-init/switch/close
  cli_scaffold.py           # init/upgrade scaffold

  current_state.py          # current-state.json / project-state.json 生成与同步
  readiness.py              # clarifying/researching readiness 评分与 gate
  presentation.py           # markdown 表格与 guided output 渲染
  paths.py                  # package/data dir 路径解析

  observation/              # 外部信号观察、候选卡片、维护闭环
  debate/                   # 多执行器辩论、round/synthesis artifacts
  executors/                # Claude/Codex/Kiro/subprocess 统一适配层
  hooks/                    # Claude Code / Agent hook surface

  retrieval.py              # 混合检索：BM25 + vector + filename score
  linker.py                 # 自动相关链接
  conflicts.py              # 记忆/笔记冲突检测
  exporter.py               # Dev Pack 导出
  web_search.py             # Brave/search/digest 相关能力
  weekly.py                 # 周期性维护入口
  launchd.py                # macOS launchd 安装辅助
  skills_sync.py            # 内置 skills 同步

  scaffold/                 # pmagent init 复制到 data_dir 的运行时 scaffold
  skills/                   # 内置 mode/step skill 合同
  templates/                # Requirement/PRD/Decision 等模板
  ops/                      # 运维说明
  vendor/                   # 打包的辅助 JS，例如 html2pptx
```

---

## 8. 运行时数据目录结构

`pmagent init --dir <data_dir>` 会初始化运行时数据目录。运行时数据目录不是源码目录，而是用户真正工作的项目库。

典型结构：

```text
<data_dir>/
  AGENTS.md
  CLAUDE.md
  MEMORY.md
  GOAL_STATE.md
  README.md
  .env
  .pmagent-version

  config/
    projects.json
    agent-workflow.yaml
    debate-executors.yaml
    executors.yaml
    watchlist.json

  memory/
  projects/
  workspaces/
  observations/
  skills/
  templates/
  ops/
  cache/
  ppt/
```

### 8.1 `config/projects.json`

负责记录：

- active project
- active workspace
- project registry
- workspace list

这是 CLI 默认上下文解析的入口。

### 8.2 `config/agent-workflow.yaml`

这是给 Agent 阅读的结构化工作流合同，定义：

- source of truth hierarchy
- phase enum
- mode enum
- artifact locations
- guided entrypoints
- debate contract
- observation contract
- gates
- skill navigation

### 8.3 `workspaces/<workspace>/.pmagent/current-state.json`

机器可读当前状态。典型字段：

```json
{
  "project": "alpha",
  "workspace": "alpha-observe",
  "mode": "zero-to-one",
  "phase": "clarifying",
  "active_step": "write-requirement",
  "pending_user_decision": "scope-confirmation",
  "next_recommended_step": { "id": "clarify_scope" },
  "artifacts": {},
  "observation": {},
  "observation_tracking": {},
  "readiness": {},
  "candidate_review": null,
  "debates": {},
  "debate_review": {},
  "debate_launch": {},
  "updated_at": "..."
}
```

### 8.4 `workspace-summary.md`

人和 Agent 都能读的压缩状态入口。它不替代 Requirement / PRD，而是用于快速恢复上下文。

内部有受控 marker：

```text
<!-- PMAGENT:SUMMARY:CORE:BEGIN -->
...
<!-- PMAGENT:SUMMARY:CORE:END -->

<!-- PMAGENT:SUMMARY:OBSERVATION:BEGIN -->
...
<!-- PMAGENT:SUMMARY:OBSERVATION:END -->
```

`summary_protocol.py` 会基于 marker 更新核心状态段和 observation 段，避免破坏用户手写内容。

---

## 9. CLI 前门设计

### 9.1 顶层命令

当前 CLI 支持：

```text
pmagent init
pmagent upgrade
pmagent retrieve
pmagent link
pmagent conflicts
pmagent export
pmagent digest
pmagent search
pmagent weekly
pmagent status
pmagent route
pmagent review
pmagent start
pmagent next
pmagent resume
pmagent clarify
pmagent research
pmagent prd status
pmagent prd
pmagent workspace-init
pmagent switch
pmagent workspace-close
pmagent skills-sync
pmagent install-launchd
pmagent observe
pmagent hook
pmagent debate
```

### 9.2 前门命令的意义

最核心的是这六个前门：

| 命令 | 作用 |
| --- | --- |
| `status` | 输出当前 workspace 的完整状态和推荐动作 |
| `route` | 推荐应该进入哪个 mode / surface / 命令 |
| `review` | 打开当前最重要的 review/status surface |
| `start` | 从 active workspace 或新 project/workspace 启动 |
| `next` | 只看下一步推荐 |
| `resume` | 恢复当前 workspace 并指明继续点 |

这套设计对 Agent 很重要：Agent 不需要猜“现在该读哪个文件”，先跑前门命令即可。

### 9.3 路由优先级

`cli_routing.py` 负责统一路由。关键优先级大致是：

```text
setup missing
-> debate failure
-> debate review
-> debate launch
-> observation candidate review / observation policy checkpoint
-> maintenance
-> clarify / research / PRD / observing
-> generic status
```

最近修复过的一个关键问题是：`next/review` 之前会让 observation policy 抢在 debate review 前面，导致和 `start/resume` 行为不一致。现在已经统一为 debate visibility gate 优先。

---

## 10. 工作流 phase 与 readiness

### 10.1 Workspace phase

| Phase | 含义 | 典型命令 |
| --- | --- | --- |
| `clarifying` | 需求澄清 | `pmagent clarify status/answer/set-scores` |
| `researching` | 调研与证据积累 | `pmagent research start/status/note/set-scores` |
| `delivery` | PRD / 交付准备 | `pmagent prd status`, `pmagent prd review/init-draft/challenge` |
| `maintaining` | observation 信号驱动的维护 | `pmagent observe maintenance-status/draft-maintenance/apply-maintenance` |

### 10.2 Readiness 评分

`readiness.py` 负责 readiness 结构化评分，例如：

- intent
- outcome
- scope
- constraints
- non_goals
- decision_boundaries
- context
- score
- threshold
- gates
- blocking_gates

它的价值是让 Agent 不只是输出自然语言判断，而是用可计算 gate 决定是否进入下一阶段。

### 10.3 Presentation 规则

`presentation.py` 会把 score / readiness 渲染为 Markdown 表格，避免 Agent 只写一段含糊总结。项目里明确强调：

- score-bearing object 必须显示原始分数；
- 表格补充解释，但不能替代分析；
- readiness gate 必须可见。

---

## 11. Observation 模块详解

Observation 是项目里最复杂、最有价值的模块之一。

### 11.1 Observation 的目的

它解决的问题是：

> 项目长期运行时，外部世界一直在变化；这些变化需要进入产品工作流，但不能直接污染 PRD。

Observation 的原则是：

```text
external signal
-> project-level observation file
-> workspace-level candidate update
-> human/agent review
-> accept/reject/snooze
-> maintenance draft
-> canonical PRD update by Agent/human
-> apply-maintenance finalization
```

### 11.2 Observation 数据结构

Project-level observation：

```text
observations/<project>/
  policy.json          # 用户确认过的观察策略：enabled/cadence/decision_status
  state.json           # 执行状态：last_run_id/last_run_at/observation_count 等
  index.json           # observation id 索引
  files/
    <observation-id>.json
  runs/
    <run-id>/
      meta.json
      query-plan.json
      raw-findings.jsonl
```

Workspace-level candidate queue：

```text
workspaces/<workspace>/candidate-updates/
  queue-summary.json
  inbox/
  accepted/
  rejected/
  snoozed/
```

Maintenance：

```text
workspaces/<workspace>/maintenance/
  drafts/
  changelog/
  consumed-cards/
```

### 11.3 Observation policy/state 分层

项目里明确区分：

| 文件 | 职责 |
| --- | --- |
| `policy.json` | 用户决策和策略，例如 enabled/cadence/decision_status |
| `state.json` | 运行状态，例如 last_run_id、observation_count |

这很重要，因为如果 state 默认值覆盖 policy，就会出现用户已经开启 daily observation，但后续 save 又变成 `enabled=false/cadence=manual` 的严重数据一致性问题。当前代码已经修复：state 不再写 policy 字段，`load_profile()` 会忽略 legacy state 中的 policy keys。

### 11.4 Observation CLI

```text
pmagent observe init-profile
pmagent observe init-workspace
pmagent observe enable
pmagent observe disable
pmagent observe set-cadence
pmagent observe plan
pmagent observe run
pmagent observe ingest
pmagent observe audit
pmagent observe unread
pmagent observe mark-read
pmagent observe review
pmagent observe accept
pmagent observe reject
pmagent observe snooze
pmagent observe maintenance-status
pmagent observe draft-maintenance
pmagent observe apply-maintenance
```

### 11.5 Observation live run 的设计

`observe run` 不是简单由 Python 直接联网抓结果。当前架构是 Agent-delegated：

1. Python 生成 query plan。
2. Python 创建 run directory。
3. Python 渲染 run-observation prompt。
4. 外部 executor（Claude / Codex / Kiro）执行搜索和阅读。
5. Agent 只能写 `raw-findings.jsonl`。
6. Agent 必须调用 `pmagent observe ingest`。
7. Python ingest 将 findings 转成 observation files 和 candidate cards。

这个设计的关键边界：

- Agent 不允许直接改 `Requirement.md`、PRD、workspace-summary、current-state。
- Agent 不允许直接写 observations index/state。
- 唯一合法写入路径是 raw findings + ingest 命令。

### 11.6 Observation 防递归与超时设计

为了避免 `observe run` 内部调用的 Agent 又递归调用 `pmagent observe run`，系统有：

- delegation lock
- inside-agent detection
- recursion guard
- timeout metadata
- parent fallback ingest
- failed delegated run guard

### 11.7 Observation review 与 maintenance

review 阶段：

```bash
pmagent observe review --workspace <workspace>
pmagent observe accept --workspace <workspace> --card <card>
pmagent observe reject --workspace <workspace> --card <card>
pmagent observe snooze --workspace <workspace> --card <card>
```

accept 后进入 maintenance：

```bash
pmagent observe maintenance-status --workspace <workspace>
pmagent observe draft-maintenance --workspace <workspace>
pmagent observe apply-maintenance --workspace <workspace>
```

`draft-maintenance` 只生成维护草稿，不自动改 PRD。真正 PRD 语义编辑由外部 Agent / 人完成。`apply-maintenance` 负责 finalize、写 changelog、消费 accepted cards、更新状态。

### 11.8 Observation 调度

`scheduler.py` 支持：

| 平台 | 后端 |
| --- | --- |
| Windows | Task Scheduler |
| macOS | launchd |
| Linux | systemd user timer |

支持 cadence：

```text
manual
weekly
weekday-morning
daily
every-12-hours
every-6-hours
```

### 11.9 Observation 最近修复点

当前代码已经处理过这些真实 smoke 暴露的问题：

- `observe run --json` 子命令语义不一致问题；
- live executor 超时失败时状态落盘；
- 防止 observe run 递归触发 agent storm；
- policy/state 分层，禁止 state 覆盖 enabled/cadence；
- accepted card 稳定驱动 maintenance next step；
- workspace-summary/current-state 同步；
- Windows 并发读写 state 的 lock / atomic write / read retry；
- `jieba/pkg_resources` warning 污染输出。

---

## 12. Debate 模块详解

Debate 是一个 side-channel，用于在 canonical 决策前引入结构化反方、正方和综合判断。

### 12.1 Debate 的目的

复杂产品决策常常需要：

- 支持方论证；
- 反对方论证；
- 多轮交锋；
- synthesis 提炼分歧、共识和建议；
- 人类 review / resolve。

Debate 模块把这些内容落到 workspace：

```text
workspaces/<workspace>/context/debates/<topic>/
  axis.json
  run.json
  status.json
  signal.json
  round-0-pro.md
  round-0-con.md
  round-1-pro.md
  round-1-con.md
  synthesis.md
  review.json
```

### 12.2 Debate CLI

```text
pmagent debate start
pmagent debate status
pmagent debate show
pmagent debate review
pmagent debate resolve
```

`debate start` 支持：

- thesis
- axis
- rounds
- foreground/background
- pro/con/synth executor override
- pro/con/synth model override

### 12.3 Debate executor 角色

| 角色 | 作用 |
| --- | --- |
| defender / pro | 支持 thesis 的论证方 |
| attacker / con | 反对 thesis 的论证方 |
| synthesizer | 综合双方观点，输出 synthesis |

默认配置目前倾向全 Claude：

```yaml
defaults:
  defender:
    exec: claude
  attacker:
    exec: claude
  synthesizer:
    exec: claude
```

用户仍可通过 `config/debate-executors.yaml` 或命令行 override 使用 Codex 等 executor。

### 12.4 Markdown-first 协议

Debate 的核心产物是 Markdown，而不是 JSON。

原因：

- 外部 Agent 更擅长稳定输出 Markdown 论证；
- 人类 review 更容易阅读；
- Git diff 更自然；
- JSON 只适合作兼容 fallback，不适合作主协议。

### 12.5 Debate 校验与失败落盘

`orchestrator.py` 会校验：

- round artifact 是否包含预期 section；
- synthesis 是否包含核心结论；
- executor 超时是否写 failed 状态；
- synthesis 缺失时 review 是否拒绝进入。

最近修复过：

- Claude 输出 heading 风格差异导致 parser 过严；
- executor 已写文件但 stdout 不符合预期时的 side-effect artifact fallback；
- synthesizer 失败时不再卡在 `synthesizing`，而是落 `failed`；
- Codex 默认 timeout 偏短导致混合执行失败，默认提高到更合理值；
- `debate show --round 1` 现在保持用户面 1-index，内部映射 round-0；
- `review/next` debate priority 与 start/resume 一致。

---

## 13. Executor 抽象层

### 13.1 为什么需要 executor 层？

Claude、Codex、Kiro CLI 的调用方式、参数、stdin/stdout、session 文件、timeout、Windows shell 行为都不一样。如果 observation 和 debate 各写一套调用逻辑，会非常混乱。

因此项目抽象出：

```text
src/pmagent/executors/
  __init__.py
  registry.py
  _subprocess.py
  _claude.py
  _codex.py
  _kiro.py
```

### 13.2 统一结果对象

Executor 返回统一 `ExecutorResult`，失败抛 `ExecutorError`。

这使上层模块可以只关心：

- content
- session_id
- timeout
- failure reason

不用关心具体 CLI 的细节。

### 13.3 Claude 适配

Claude 相关适配考虑了：

- Windows `.cmd` 调用；
- Git Bash discovery；
- prompt 通过 stdin 传递，避免 Windows command line too long；
- timeout；
- session id。

### 13.4 Codex 适配

Codex 相关适配考虑了：

- `codex exec`；
- `--output-last-message`；
- session file 读取；
- trusted / untrusted sandbox 策略；
- Windows 超时更明显的问题。

### 13.5 Kiro 适配

Kiro 作为 observation 可用 backend，通过 registry 自动探测。

### 13.6 Registry

`registry.py` 负责：

- normalize executor id；
- detect inside agent；
- resolve available backend；
- precheck executor plan；
- run executor。

---

## 14. Hooks 体系

`src/pmagent/hooks/` 是面向 Claude Code / Agent runtime 的 hook surface。

```text
hooks/
  _common.py
  session_bootstrap.py
  state_surface.py
  pre_bash_guard.py
  pre_write_guard.py
  post_mutation_check.py
  response_validator.py
```

### 14.1 session_bootstrap

会话启动时注入：

- base context；
- workspace summary；
- selected current-state fields；
- debate attention；
- audit info。

### 14.2 state_surface

在 Agent 需要状态时注入：

- status block；
- observation backlog；
- debate backlog；
- debate failures；
- debate launch pending。

### 14.3 pre_write_guard

保护 canonical 文档边界，例如：

- `Requirement.md`
- `prd/**`
- candidate update / maintenance 相关边界

### 14.4 pre_bash_guard

用于拦截风险命令或要求确认，例如候选卡片处理、canonical mutation 等。

### 14.5 post_mutation_check

写入后检查：

- workspace-summary 是否同步 current-state；
- raw log 是否记录；
- 状态是否过旧。

### 14.6 response_validator

用于确保 Agent 回复中不要丢失评分表、readiness 分数等结构化信息。

---

## 15. 检索、链接、冲突与导出

### 15.1 Retrieval

`retrieval.py` 实现混合检索：

- BM25
- jieba 中文分词
- filename keyword score
- sqlite-vec vector search
- OpenAI embeddings

支持：

```bash
pmagent retrieve --query "..." --mode hybrid
pmagent retrieve --query "..." --mode bm25
pmagent retrieve --query "..." --mode vector
```

### 15.2 Linker

`linker.py` 自动扫描文档并更新 Related links：

- 扫描 memory / decisions / research / strategy / prd / context；
- 计算语义相关度；
- 添加双向链接；
- 支持 dry-run / reindex。

### 15.3 Conflicts

`conflicts.py` 用于检测记忆或笔记之间的潜在冲突：

- tokenization；
- TF-IDF；
- cosine similarity；
- contradiction signal；
- optional LLM judge。

### 15.4 Exporter

`exporter.py` 导出 Dev Pack，用于把当前 workspace 的 PRD、上下文、决策、manifest 等整理成研发可消费包。

### 15.5 Web Search / Digest / Weekly

`web_search.py` 和 `weekly.py` 提供：

- Brave Search 封装；
- watchlist；
- digest；
- weekly maintenance routine。

---

## 16. Scaffold、Skills 与 Templates

### 16.1 Scaffold

`src/pmagent/scaffold/` 是 `pmagent init` 复制到运行时 data dir 的基础文件：

```text
scaffold/
  AGENTS.md
  CLAUDE.md
  GOAL_STATE.md
  MEMORY.md
  README.md
  .claude/settings.json
  .codex/config.toml.example
  config/
    agent-workflow.yaml
    debate-executors.yaml
    executors.yaml
    projects.json
    watchlist.json
```

它定义了运行时 Agent 应该如何理解这个数据目录。

### 16.2 Skills

`src/pmagent/skills/` 是内置工作合同：

```text
skills/
  modes/
    zero-to-one/
    conviction-forge/
  steps/
    write-requirement/
    do-research/
    do-competitive-analysis/
    write-strategy/
    write-prd/
    challenge-prd/
    write-decision/
    write-testcase/
    export-devpack/
    candidate-review/
    run-observation/
    ...
```

Skills 不是顶层 router；顶层 router 是 CLI + AGENTS + workflow config。Skills 更像“当已知要做某一步时，告诉 Agent 该读什么、写什么、边界是什么”。

### 16.3 Templates

`templates/` 包含：

- DECISION_TEMPLATE.md
- MEMORY_TEMPLATE.md
- PRD_TEMPLATE.md
- QUALITY_LOG_TEMPLATE.md
- REQUIREMENT_TEMPLATE.md
- RESEARCH_TEMPLATE.md
- STRATEGY_TEMPLATE.md
- TESTCASE_TEMPLATE.md
- WORKFLOW_CONTRACT_TEMPLATE.md
- WORKSPACE_SUMMARY_TEMPLATE.md

---

## 17. 关键执行流程

### 17.1 初始化流程

```text
pmagent init --dir <data_dir>
-> 创建运行时目录
-> 写入 global config
-> 复制 scaffold
-> 同步 skills/templates/ops
```

### 17.2 Workspace 启动流程

```text
pmagent workspace-init --project alpha --workspace alpha-observe
-> 创建 projects/alpha
-> 创建 workspaces/alpha-observe
-> 写 Requirement.md
-> 写 workspace-summary.md
-> 更新 config/projects.json
-> 初始化 observation scaffold
-> 写 .pmagent/current-state.json
```

### 17.3 Agent 恢复流程

```text
pmagent resume
-> 读取 active workspace
-> preview current-state
-> 检查 debate failure/review/launch
-> 检查 observation backlog/policy/maintenance
-> 输出 guided_view + suggested_command
```

### 17.4 Observation 闭环

```text
observe plan
-> observe run
-> raw-findings.jsonl
-> observe ingest
-> observation files
-> candidate-updates/inbox
-> observe review
-> accept/reject/snooze
-> maintenance-status
-> draft-maintenance
-> human/Agent edits canonical PRD
-> apply-maintenance
```

### 17.5 Debate 闭环

```text
debate start
-> precheck executors
-> create topic dir
-> round-N-pro.md / round-N-con.md
-> synthesis.md
-> debate review
-> debate resolve --accepted/--rejected/--deferred
-> current-state debate_review cleared
```

---

## 18. 状态一致性与并发设计

### 18.1 为什么需要锁和原子写？

Windows 上多个命令并发读写 `.pmagent/current-state.json` 或 `workspace-summary.md` 时，可能出现：

- PermissionError；
- 半写入读取；
- marker 校验 transient fail；
- lock file 残留。

### 18.2 当前策略

`current_state.py` 与 `summary_protocol.py` 中实现了：

- lock file；
- stale lock cleanup；
- atomic temp file + `os.replace`；
- read retry/backoff；
- JSON decode retry；
- summary marker validation。

### 18.3 current-state 与 summary 同步

`sync_current_state()` 会：

1. preview 当前状态；
2. merge patch；
3. infer readiness；
4. refresh artifacts / observation / debate snapshot；
5. 写 current-state；
6. 如果 workspace-summary marker valid，同步 core section 和 observation section。

---

## 19. 测试体系

当前测试文件：

```text
tests/test_cli.py
tests/test_cli_subsystems.py
tests/test_debate_timeouts.py
tests/test_executors.py
tests/test_hooks.py
tests/test_host_agent_scaffold.py
tests/test_init_upgrade.py
tests/test_observation_agent.py
tests/test_observation_cli.py
tests/test_observation_scheduler.py
tests/test_paths.py
tests/test_presentation.py
tests/test_readiness.py
tests/test_switcher.py
```

### 19.1 覆盖重点

| 测试文件 | 覆盖内容 |
| --- | --- |
| `test_cli.py` | 顶层 CLI 命令存在性 |
| `test_cli_subsystems.py` | route/status/review/start/resume、workspace-init、debate、PRD、research 等综合流 |
| `test_debate_timeouts.py` | debate timeout 与失败落盘 |
| `test_executors.py` | Claude/Codex/Kiro executor 行为 |
| `test_hooks.py` | hook 注入、状态 surface、guard |
| `test_init_upgrade.py` | init/upgrade scaffold 行为 |
| `test_observation_agent.py` | observation delegated agent contract |
| `test_observation_cli.py` | observation CLI、review、maintenance、并发状态同步 |
| `test_observation_scheduler.py` | Windows/macOS/Linux 调度命令 |
| `test_presentation.py` | Markdown table / guided output |
| `test_readiness.py` | readiness score/gate |
| `test_switcher.py` | project/workspace switching |

### 19.2 当前质量信号

- 全量测试：`173 passed`
- 关键 smoke 事实：observation 主流程、debate 主流程、mixed Claude+Codex 在提高 timeout 后可跑通
- 已对 Windows 状态文件锁竞争做回归测试

---

## 20. 这个项目里最有技术含量的点

### 20.1 Agent 工作流状态机

项目不是简单 CLI，而是把 PM 流程抽象成可恢复状态机：

- phase
- active_step
- pending_user_decision
- next_recommended_step
- readiness gates
- observation backlog
- debate backlog

这让外部 Agent 能跨会话继续工作。

### 20.2 Markdown + JSON 双层状态协议

同时维护：

- 给人看的 Markdown summary
- 给机器看的 JSON state

并通过 marker、锁、原子写、retry 保证同步。

### 20.3 外部 Agent 执行边界

Observation 和 Debate 都需要调用外部 Agent，但又不能让它随意写项目文件。因此项目设计了：

- executor abstraction
- prompt contract
- allowed write path
- validation
- failure metadata
- review gates

### 20.4 Cross-platform CLI 稳定性

真实处理了：

- Windows `.cmd` 行为；
- command line too long；
- stdin prompt；
- timeout；
- file lock；
- Git Bash discovery；
- Task Scheduler；
- launchd / systemd。

### 20.5 Debate markdown parser 容错

外部 Agent 输出格式不稳定。项目需要兼容不同 heading 风格、side-effect artifact、partial output，并在失败时正确落盘。

### 20.6 Observation policy/state 数据一致性

项目修复了 policy/state 混写导致用户开启状态被静默覆盖的问题。这体现了对“配置”和“运行状态”分层的工程敏感度。

---

## 21. 可以如何对别人介绍这个项目

### 21.1 30 秒版本

我做了一个叫 `pmagent` 的 Python CLI 项目，它相当于给 Claude Code / Codex 这类外部 Agent 加了一层产品管理运行时。它用本地 Markdown + JSON 文件协议管理 project/workspace 状态，提供 `status/review/next/resume` 这类前门命令，让 Agent 跨会话知道项目当前处于澄清、调研、PRD、维护哪个阶段。项目还实现了 observation 外部信号闭环和 debate 多视角辩论闭环，支持 Claude/Codex/Kiro executor、Windows/macOS/Linux 调度，以及完整的状态同步和测试。

### 21.2 2 分钟版本

这个项目的核心是解决 AI Agent 做长期产品项目时的上下文断裂和文档污染问题。我把长期知识和单轮需求拆成 project/workspace 双层模型：project 存长期战略、决策和 observation；workspace 存本轮 Requirement、research、PRD、current-state、candidate updates 和 maintenance。

Agent 进入项目时不需要猜该读什么，而是跑 `pmagent status`、`review`、`next`、`resume`。CLI 会基于 `current-state.json`、`workspace-summary.md`、observation backlog、debate backlog 计算下一步。

我还实现了两个关键闭环：

1. Observation：外部信号先进入 project-level observation，再进入 workspace candidate queue，经用户 accept/reject/snooze 后才生成 maintenance draft，不直接改 PRD。
2. Debate：用 defender/attacker/synthesizer 多 executor 生成 round artifacts 和 synthesis，然后进入 review/resolve。

工程上做了 executor abstraction，适配 Claude、Codex、Kiro；做了跨平台 scheduler；做了 Windows 文件锁和 atomic write；并用 pytest 覆盖 173 个测试。

### 21.3 5 分钟深聊版本

可以从下面几个角度讲：

1. **为什么不是普通文档系统**：因为 Agent 需要稳定状态、工作流路由和写入边界，不只是模板。
2. **为什么采用本地文件协议**：Markdown 方便人类 review，JSON 方便机器读，YAML 方便配置，Git 友好，可审计。
3. **project/workspace 为什么分层**：长期知识和本轮需求生命周期不同；observation 是 project-level，但 candidate update 是 workspace-level。
4. **observation 为什么不直接改 PRD**：外部信号可能是假阳性或暂不相关，必须先 review，再 maintenance。
5. **debate 为什么 markdown-first**：Agent 输出自然语言论证更稳定，且人类更容易 review；JSON 只做兼容 fallback。
6. **Windows 为什么是难点**：CLI、`.cmd`、路径、file lock、Task Scheduler、timeout 行为都和类 Unix 不同，项目做了专门处理。
7. **质量保障**：通过 tests 锁定真实 smoke 暴露的问题：executor timeout、state sync、route priority、policy/state layering、round indexing 等。

---

## 22. 简历写法建议

### 22.1 中文简历版本

**PM Agent Runtime / AI Agent 产品管理工作流 CLI**

- 设计并实现一个 Python CLI-first 的 AI Agent 产品管理运行时，为 Claude Code / Codex / Kiro 等外部 Agent 提供跨会话状态恢复、需求澄清、调研、PRD、维护和交付导出能力。
- 抽象 project/workspace 双层数据模型，基于 Markdown + JSON + YAML 本地文件协议管理长期项目知识、当前 workspace 状态、readiness gate、observation backlog 和 debate backlog。
- 实现 `status / route / review / start / next / resume` 统一前门路由，根据 phase、pending decision、observation、debate 自动推荐下一步，降低 Agent 在长期任务中的上下文漂移。
- 构建 observation 外部信号闭环：支持 Agent-delegated 搜索、raw findings ingest、candidate update review、accept/reject/snooze、maintenance draft 和 changelog finalization，避免外部信号直接污染 canonical PRD。
- 构建 debate 多视角辩论系统：支持 defender/attacker/synthesizer 多 executor、round markdown artifacts、synthesis、review/resolve、失败落盘和 timeout 控制。
- 封装 Claude / Codex / Kiro CLI executor 适配层，处理 Windows `.cmd`、stdin prompt、session capture、timeout、sandbox/trust mode 和跨平台兼容问题。
- 实现 Windows Task Scheduler、macOS launchd、Linux systemd user timer 的 observation 调度支持，并通过 atomic write、file lock、read retry 保障 Windows 并发状态同步稳定性。
- 建立 pytest 测试体系覆盖 CLI routing、observation、debate、executors、hooks、scheduler、readiness、presentation、init/upgrade 等模块，当前全量测试 173 passed。

### 22.2 英文简历版本

**PM Agent Runtime — CLI-first workflow runtime for AI coding/product agents**

- Built a Python CLI-first product-management runtime for external AI agents such as Claude Code, Codex, and Kiro, enabling resumable long-running product workflows across requirement clarification, research, PRD drafting, observation, maintenance, debate, and delivery export.
- Designed a project/workspace data model backed by local Markdown, JSON, and YAML protocols to separate long-term product knowledge from per-workspace execution state.
- Implemented unified front-door commands (`status`, `route`, `review`, `start`, `next`, `resume`) that route agents to the correct workflow surface based on phase, readiness gates, observation backlog, and debate review state.
- Built an observation pipeline for external signals: agent-delegated research, raw findings ingestion, candidate update queues, accept/reject/snooze review, maintenance drafts, changelog finalization, and PRD-safe update boundaries.
- Built a debate workflow with defender/attacker/synthesizer executors, markdown-first round artifacts, synthesis generation, review/resolve lifecycle, timeout handling, and failure persistence.
- Created a cross-executor abstraction for Claude, Codex, and Kiro CLIs, handling Windows `.cmd` quirks, stdin-based prompts, session capture, timeouts, sandbox/trust modes, and fallback behavior.
- Added cross-platform scheduling via Windows Task Scheduler, macOS launchd, and Linux systemd user timers, plus atomic state writes and retry/backoff for Windows file-lock reliability.
- Maintained a pytest suite covering CLI routing, observation, debate, executors, hooks, scheduler, readiness scoring, presentation, and scaffold upgrades, with 173 passing tests.

### 22.3 如果简历只能写两条

- 设计并实现 Python CLI-first 的 AI Agent PM Runtime，用 Markdown/JSON/YAML 本地协议管理 project/workspace 状态，为 Claude/Codex/Kiro 提供 `status/review/next/resume` 跨会话工作流路由。
- 构建 observation 外部信号闭环与 debate 多视角辩论闭环，封装多 Agent CLI executor，支持跨平台调度、Windows 文件锁稳定性和 173 个 pytest 回归测试。

---

## 23. 面试 / 交流时可重点展开的问题

### 23.1 为什么选择 CLI-first，而不是 Web App？

因为目标用户是外部 Agent 和 power user。CLI：

- 可脚本化；
- 可被 Agent 调用；
- 易测试；
- 易接入本地文件系统；
- 与 Git / Markdown 协议天然兼容。

Web UI 可以以后再做，但核心协议和状态机必须先稳定。

### 23.2 为什么选择 Markdown + JSON，而不是数据库？

- Markdown：人类可读、Agent 易读、Git diff 友好。
- JSON：机器可读、状态结构稳定。
- YAML：配置友好。
- 本地文件降低部署成本，适合个人 Agent runtime。

### 23.3 为什么 observation 不自动改 PRD？

因为外部信号有不确定性，自动改 canonical artifact 风险高。项目采用：

```text
signal -> candidate -> review -> maintenance -> canonical edit -> finalization
```

这符合产品治理原则。

### 23.4 为什么 debate 是 side-channel？

Debate 产生观点和 synthesis，但不直接改变需求或 PRD。它必须经过 review/resolve，这样可以避免多 Agent 自动辩论结果直接污染主线。

### 23.5 项目最大的工程难点是什么？

1. Agent 输出不稳定，需要 parser 和 fallback。
2. Windows CLI / file lock / timeout 问题多。
3. 状态同步要兼顾人类 Markdown 和机器 JSON。
4. 需要防止 Agent 递归调用自己造成进程风暴。
5. 要把“产品流程”抽象成可测试状态机，而不是散乱提示词。

---

## 24. 当前项目状态与后续演进方向

### 24.1 当前已经具备

- Python package + CLI
- project/workspace scaffold
- current-state / workspace-summary 同步
- readiness scoring
- front-door routing
- observation full loop
- debate full loop
- Claude/Codex/Kiro executor abstraction
- cross-platform scheduler
- hooks
- retrieval/linking/export
- pytest regression suite

### 24.2 可继续增强

后续可以继续做：

1. **更强的 UI / TUI**：在 CLI 协议稳定后，增加 terminal dashboard 或 Web UI。
2. **更丰富的 debate trigger**：在 PRD challenge、重大 strategy change、observation high-risk signal 时自动建议 debate。
3. **更强的 observation source adapters**：除搜索外接入 RSS、GitHub、Linear、Slack、App Store review 等。
4. **更系统的 memory promotion**：workspace-close 后把稳定结论自动提升到 project/global memory。
5. **更完整的 Agent plugin integration**：对 Claude Code / Codex hooks 做更深集成。
6. **真实用户项目压测**：用多个长期项目验证 project/workspace 双层模型的长期可维护性。

---

## 25. 项目总结

`pmagent` 的本质不是“帮你写 PRD 的脚本”，而是一套 **让 AI Agent 可以长期、可恢复、可审计地参与产品管理工作的运行时协议**。

它的亮点在于：

- 把 PM 工作流抽象成 CLI 状态机；
- 把长期知识和单轮需求拆成 project/workspace；
- 把 Agent 输出控制在安全写入边界内；
- 把外部变化纳入 observation review/maintenance 闭环；
- 把复杂决策纳入 debate review/resolve 闭环；
- 兼顾 Windows/macOS/Linux 和 Claude/Codex/Kiro 多 executor；
- 用测试覆盖真实 smoke 中暴露的状态同步、路由优先级、timeout、parser、文件锁问题。

如果在简历或面试里讲，这个项目可以定位为：

> 一个面向 AI Agent 的本地产品管理操作系统 / runtime，核心能力是工作流状态机、长期记忆、外部信号治理、多 Agent 辩论、跨平台执行器适配和可审计文件协议。
