# PMA / pmagent

PMA 是一套面向 AI Agent 的产品管理协议。

它帮助 Claude Code、Codex 等外部 Agent 长期推进真实项目：把需求、调研、决策、PRD、观察信号和交付上下文，从零散聊天变成可落盘、可恢复、可审计、可复盘的文件系统。

一句话说：

> PMA 不是让 AI 替你做产品经理，而是让人和 Agent 有一套稳定协作协议。

## 1. PMA 解决什么问题

AI 已经很会写代码、写文档、做总结，但真实项目依然容易卡住。

常见问题是：

- 需求散在聊天记录里，下一轮 Agent 无法恢复上下文
- PRD、调研、决策、开发切片之间没有稳定关系
- 项目推进到一半，没人说得清当前阶段和下一步
- 外部反馈、观察信号、协作者评论无法进入统一 review 流程
- Agent 很会执行任务，但缺少长期维护项目语义状态的协议
- 人的判断、取舍和复盘没有被系统性沉淀

PMA 要解决的是：

> 让产品工作从聊天流，变成状态化的项目工作流。

## 2. PMA 的核心关系

PMA 里有三个角色：

```text
人
  负责判断、取舍、优先级和最终品味

Agent
  负责维护上下文、推进流程、整理证据、暴露风险

PMA 文件协议
  负责把项目状态、需求共识、决策和产物稳定落盘
```

也可以理解为：

```text
Human taste
  ↑
PMA workflow protocol
  ↑
Local PM Data files
  ↑
Claude Code / Codex / other agents
```

PMA 不替代 Claude Code、Codex 或其他外部 Agent。它给这些 Agent 一个长期项目上下文和工作边界。

## 3. 三层架构：道、术、器

PMA 可以按三层理解。

### 道：人保留最终判断

产品工作里最重要的不是生成更多文档，而是判断：

- 什么问题值得做
- 什么边界不能破
- 什么需求应该暂缓
- 什么方案值得赌
- 什么反馈应该采纳
- 什么取舍符合产品品味

PMA 的基本立场是：这些判断最终仍然属于人。

Agent 可以辅助分析、组织证据、提出建议，但不直接替人做最终取舍。PMA 的目标是让 Agent 维护上下文、组织证据、暴露冲突、推动复盘，把人从杂乱执行中解放出来，让人更专注在 taste 上。

### 术：把产品工作变成协议

PMA 把产品工作拆成一组可恢复的工作面：

```text
clarify
  澄清需求边界

write-requirement
  沉淀稳定需求共识

research
  补齐证据和外部上下文

write-prd
  生成可交付 PRD

dev-readiness
  拆解研发可执行切片

observe
  持续接收外部变化

maintenance
  判断是否需要更新需求或 PRD
```

每个工作面都有明确的输入、输出、状态文件和推进规则。

### 器：用文件系统承载长期上下文

PMA 的事实源是本地 PM Data 目录。

核心文件包括：

```text
Requirement.md
  稳定需求共识

workspace-summary.md
  给下一轮 Agent 读取的压缩摘要

.pmagent/current-state.json
  机器可读的当前状态

context/
  原始澄清记录和上下文

research/
  调研记录和证据

decisions/
  关键决策

prd/
  PRD 文档

candidate-updates/
  外部建议和观察卡片

exports/
  面向研发或协作者的导出包
```

这些都是普通文件，可以被 Git 管理，可以被人阅读，也可以被 Agent 检索和继续消费。

## 4. PMA 如何组织项目上下文

PMA 用一套固定文件结构组织项目上下文。

```text
projects/
  <project>/
    长期项目资产：背景、策略、决策、研究

workspaces/
  <workspace>/
    当前推进上下文：Requirement、Research、PRD、状态、外部建议
```

一个 `Project` 是长期项目；一个 `Workspace` 是这个项目下的一次具体推进。

例如：

```text
projects/
  glucose-diet-assistant/
  prodtech-agent/

workspaces/
  glucose-diet-assistant-mvp-requirement/
  prodtech-agent-pm-infra/
```

在 Workspace 里，PMA 主要维护这些文件：

| 文件 / 目录                     | 作用                           |
| ------------------------------- | ------------------------------ |
| `Requirement.md`              | 当前需求共识                   |
| `workspace-summary.md`        | 给下一轮 Agent 的摘要          |
| `.pmagent/current-state.json` | 给机器读的状态                 |
| `context/`                    | 澄清记录、原始问答、讨论上下文 |
| `research/`                   | 调研记录和证据                 |
| `decisions/`                  | 关键决策                       |
| `prd/`                        | PRD 文档                       |
| `candidate-updates/`          | 外部建议和观察卡片             |
| `exports/`                    | 面向研发或协作者的导出包       |

PMA 的核心不是某一份文档，而是这些文件之间的关系：

```text
聊天 / 观察 / 调研
  -> Requirement
  -> Research
  -> Decisions
  -> PRD
  -> Dev Pack
  -> Observation / Maintenance
```

这套结构让下一轮 Agent 不需要重新读完整聊天记录，也能恢复当前项目状态。

## 5. Candidate Card：外部信号入口

真实项目不会只靠一次需求澄清推进。

后续还会不断出现：

- 协作者评论
- 用户反馈
- 外部调研
- 竞品变化
- 分析 Agent 的建议
- 跨项目复用机会
- Agent 自身执行过程中的风险提示

PMA 不允许这些外部信号直接改 PRD。所有外部信号都应该先进入 Candidate Card：

```text
Feishu Base
  -> pmagent infra pull-cards --from-base
  -> candidate-updates/inbox
  -> pmagent review
  -> accepted / rejected / snoozed
```

本地 review 队列的主来源是 `candidate-updates/inbox/*.md`。旧的 `observations/<project>/index.json` 只作为 legacy/local-only 兼容来源保留。

```text
inbox -> accepted / rejected / snoozed
```

只有被人 review 之后，才可能进入 Requirement、PRD 或 decisions。

这保证了一个核心原则：

> 外部信号可以建议，但不能越过人的判断直接改写项目事实源。

## 6. 典型工作流

一个 workspace 通常这样推进：

```text
1. workspace-init
   创建项目工作区

2. clarify
   澄清问题、目标、边界、非目标

3. write-requirement
   写入稳定需求共识

4. research
   补齐调研、竞品、技术、用户或业务证据

5. write-prd
   生成可交付 PRD

6. dev-readiness
   拆解研发可执行切片

7. observe / maintenance
   持续接收外部变化，判断是否需要更新需求或 PRD
```

PMA 的重点不是“一次性生成 PRD”，而是让项目可以持续推进、恢复和复盘。

## 7. 快速开始

如果你想快速体验 PMA，其实不用一上来就理解里面所有的协议、状态机和文件结构。

最简单的方式是：先把它当成一个“产品经理工作目录”来用。你把一个真实需求丢进去，然后让 Claude Code、Codex 这类 Agent 按 PMA 的方式帮你推进一轮。

### 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### 2. 初始化 PM Data

```bash
pmagent init --dir ~/pm-data
```

这一步会创建一个 PM Data 目录。后面你的项目、需求、调研、决策、PRD、开发切片和观察信号，都会沉淀在这个目录里。

### 3. 在 Agent 中打开 PM Data

然后在 Claude Code / Codex 里打开这个目录：

```bash
cd ~/pm-data
```

接下来不用背命令，直接用自然语言说你要做什么。例如：

```text
我想做一个饮食助手 MVP，帮我用 PMA 流程推进需求澄清和 PRD。
```

Agent 会读取 PMA 的 `AGENTS.md`、`config/agent-workflow.yaml` 和当前状态文件，然后开始帮你做几件事：

- 创建 project / workspace
- 澄清需求
- 写入 `Requirement.md`
- 维护 `workspace-summary.md`
- 推进 research / PRD
- 处理 observation / candidate card
- 在需要时导出交付材料

你可以把这个过程理解成：以前你是在聊天窗口里和 AI 讨论需求；现在你是在一个有状态、有文件协议、有恢复能力的工作区里推进项目。

真正上手的时候，建议不要拿一个假需求测试。直接拿你手上一个正在做、还没完全想清楚的需求开始。PMA 的价值不是生成一份漂亮文档，而是在反复澄清、推翻、补证据、写决策、改 PRD 的过程中，把这些上下文都稳稳地留下来。

如果中途断了也没关系，下一次重新打开目录，直接说：

```text
继续这个 workspace，看看当前状态和下一步。
```

Agent 会从状态文件和摘要里恢复现场，而不是靠你重新讲一遍来龙去脉。

## 8. Agent 使用的协议入口

PMA 底层仍然是 CLI，但这些命令主要是给 Agent 调用的协议入口，而不是要求用户每天手工执行。

### 状态与导航

```bash
pmagent status
pmagent review
pmagent next
pmagent resume
```

Agent 用这些命令判断：

- 当前 workspace 在哪个阶段
- 是否有待处理的 observation
- 下一步应该进入哪个工作面
- 是否可以进入 PRD 或开发准备

### 阶段推进

```bash
pmagent clarify status
pmagent research status
pmagent prd status
```

Agent 用这些命令读取当前阶段状态，再决定应该问问题、补 research，还是生成 PRD。

### 外部信号与基础设施

```bash
pmagent infra auth-guide --brand lark --app-id <approved-app-id> --json
pmagent infra bootstrap --project <project> --json
pmagent infra pull-cards --from-base --workspace <workspace> --json
pmagent review
pmagent infra sync-status
pmagent infra wiki-push
```

已有 Feishu Base 时可以绑定现有表：

```bash
pmagent infra bootstrap --project <project> \
  --adopt-existing-base \
  --base-token <base-app-token> \
  --table-id <table-id> \
  --json
```

Agent 用这些命令处理 Candidate Card relay、飞书同步和协作层状态。`pmagent observe run` / `observe enable` / `observe set-cadence` 仍保留，但定位是 legacy/local-only observation，不是默认外部信号入口。

一般情况下，用户只需要告诉 Agent 想做什么；Agent 会根据 PMA 协议选择合适命令。

## 9. 和普通 PRD 模板有什么不同

普通 PRD 模板规定“文档长什么样”。

PMA 规定“产品工作如何持续推进”。

| 问题                      | PMA 的处理方式                                          |
| ------------------------- | ------------------------------------------------------- |
| 当前需求共识是什么        | 写入 `Requirement.md`                                 |
| 下一轮 Agent 怎么恢复状态 | 读取 `workspace-summary.md` 和 `current-state.json` |
| 调研证据放哪里            | 写入 `research/`                                      |
| 关键取舍怎么沉淀          | 写入 `decisions/`                                     |
| 外部反馈怎么进入流程      | 转成 Candidate Card                                     |
| 什么能改 PRD              | 必须经过 review 和 maintenance                          |
| 当前下一步是什么          | 由 `status / review / next` 暴露                      |

PMA 不是文档模板，而是人和 Agent 的协作协议。

## 10. 基础设施扩展

PMA 的本地文件系统是事实源。

在更完整的协作形态中，可以接入：

```text
Local PM Data Git repo
  ├── GitHub
  │     机器全量镜像，给分析 Agent 读取
  │
  ├── Feishu Wiki
  │     人可读镜像，用于展示、协作和评论
  │
  └── Feishu Base
        Candidate Card 中转层
```

### GitHub

GitHub 保存 PM Data 的机器全量镜像。

它适合给分析 Agent、跨设备工作流和长期元分析任务读取。

### Feishu Wiki

飞书 Wiki 展示人可读文档。

它适合协作者阅读 Requirement、Research、Decision、PRD 和 Workspace Summary。

飞书不是事实源，本地 Git 才是事实源。

### Feishu Base

飞书 Base 承载 Candidate Card。

所有观察、评论、建议、分析结果都可以统一进入卡片表，再由 PMA 拉回本地 review。

默认链路是：

```bash
pmagent infra pull-cards --from-base --workspace <workspace> --json
pmagent review
pmagent infra review-card --workspace <workspace> --card <card-id> --status accepted --note "<note>" --json
pmagent infra push-feedback --workspace <workspace> --json
```

### Advisor Agent（军师）

Advisor Agent 是 PMA 的元分析层。在中文语境里，我们也把它叫做“军师”。

它不是另一个替你写 PRD 的执行 Agent，而是一个站在项目系统外侧做复盘和诊断的分析 Agent。它读取 PM Data，分析人的行为模式、项目卡点、跨项目复用机会和 Agent 运转效率。

Advisor Agent 不直接改 PMA，不自动修改 Requirement 或 PRD。它只产出 Candidate Card，由人决定是否采纳。

## 11. 适合谁

PMA 适合：

- 用 Claude Code / Codex 长期推进真实项目的人
- 希望把 AI 协作从聊天升级成项目工作流的人
- 同时管理多个需求、多个 workspace、多个 PRD 的人
- 希望 Agent 能恢复上下文，但不想放弃判断权的人
- 希望沉淀需求、调研、决策、PRD 和复盘资产的人

## 12. 设计原则

- **Local-first**：本地 PM Data 是事实源
- **File protocol first**：用普通文件承载长期语义
- **Single Writer**：PMA 是 canonical 文件写入边界
- **Human-in-the-loop**：关键变化必须经过人 review
- **Review before mutation**：外部信号不直接改 PRD
- **Agent-native**：命令和状态为外部 Agent 设计
- **Recoverable workflow**：任何一轮会话都应能恢复当前状态
- **Decision over chatter**：关键取舍写成 decision，而不是淹没在聊天里

## 13. 当前状态

PMA 仍处于早期阶段，但核心框架已经成型：

- project / workspace 双层模型
- Requirement / Research / Decision / PRD 文件协议
- `workspace-summary.md` / `current-state.json` 状态入口
- clarify / research / prd / observe 主链路
- Candidate Card 建议通道
- Feishu / GitHub / Advisor Agent 基础设施设计

它的目标不是做一个更漂亮的 PM 工具，而是给 Agent 时代的产品工作建立一套可靠的上下文协议。

## License

Proprietary.
