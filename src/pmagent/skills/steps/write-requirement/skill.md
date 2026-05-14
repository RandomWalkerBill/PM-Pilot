# Skill: 写需求（创建/更新 Requirement + Workspace）

## Description

**把一个模糊需求落成可追踪的 workspace 入口，并为后续 research / PRD 建好基础状态。**

## 触发条件

- 用户发起新需求讨论，Agent 判断需要落文档
- 用户明确说"新建需求"或"开个新 workspace"
- 0-to-1 / 迭代模式的流程起点

## Step Contract（协议边界）

- **Reads**：`config/projects.json`、已有 `Requirement.md`、当前对话上下文。
- **Writes**：`Requirement.md`、`context/`、`decisions/`、必要时新建 `projects/<project>/` 与 `workspaces/<workspace>/`。
- **May mutate**：`config/projects.json`、当前 workspace 的 `workspace-summary.md`。
- **Must not mutate**：无关 project/workspace 的文件。
- **Required user confirmation**：Project 路由不唯一、Workspace 复用不确定、需求边界不清晰时必须确认。
- **Handoff**：交给 Research/Strategy/PRD 前，必须留下清晰的一句话需求、非目标/约束缺口、下一步推荐。

## 前置检查

1. 读取 `config/projects.json`，确认当前项目列表与 workspace 状态。
2. 通过关键词匹配确定目标 Project：
   - 唯一命中 → 自动路由
   - 多命中或无命中 → 向用户确认
3. 判断 Workspace 复用 vs 新建：
   - 检查该 Project 下已有 workspace 的 Requirement.md "一句话需求"
   - 新需求能放进已有的一句话 → 复用
   - 放不进 → 新建
   - 拿不准 → 回显两个选项让用户选

## 执行步骤

### Step 1: 澄清需求

从对话中提取：
- 一句话描述（为谁解决什么问题）
- 背景与动机
- 关键约束（技术/时间/资源/依赖）
- 优先级

如信息不足，逐条向用户确认（一次问 1 个问题）。

### Step 2: 创建 Project（如需新建）

如果前置检查判断需要新建 Project：
- 创建 `projects/<project>/` 及标准子目录：`strategy/`、`decisions/`、`memory/`、`research/`、`exports/`、`background/`
- 创建 `projects/<project>/PROJECT.md`（项目知识中枢，含项目名、简述、关键词）
- 更新 `config/projects.json`：添加新 project 条目（含 `description`、`keywords`、`workspaces` 数组）

如 Project 已存在，跳过此步。

### Step 3: 创建 Workspace（如需新建）

- 目录名：用英文短横线命名（如 `user-onboarding-v2`）
- 创建标准子目录：`strategy/`、`decisions/`、`research/`、`context/`、`prd/`、`exports/`
- 创建或更新 `workspace-summary.md`（可参考 `templates/WORKSPACE_SUMMARY_TEMPLATE.md`）：
  - `Current Goal`：一句话需求
  - `Current State`：`clarifying`
  - `Open Questions`：仍待澄清的问题
  - `Important Links`：指向 `Requirement.md`

### Step 4: 回溯对话内容落盘

> **核心原则**：落文档是回溯动作。Agent 必须扫描本次对话中 **所有已产生的内容**，分类写入 workspace，而非只处理触发点之后的新内容。

扫描当前对话，将有价值的内容分类落盘：
- **澄清阶段原始问答** → `workspaces/<workspace>/context/clarifying-log.md`
- **调研阶段原始记录** → `workspaces/<workspace>/research/research-log.md`
- **调研类产物**（行业数据、竞品信息、技术调研文档）→ `workspaces/<workspace>/research/`
- **上下文类**（事实性约束、关键共识、外部输入）→ `workspaces/<workspace>/context/`
- **决策类**（对话中已达成的方向性决定）→ `workspaces/<workspace>/decisions/`

其中：

- `context/clarifying-log.md` 是 clarifying 阶段的全量原始问答历史
- `research/research-log.md` 是 researching 阶段的全量原始记录历史
- 不再维护 workspace 级全局聊天记录文件

如果对话中尚无有价值的素材，跳过此步（后续模式流程会补齐）。

### Step 5: 写 Requirement.md

> **核心原则**：`Requirement.md` 的正文维护权属于 Agent。pmagent CLI 不写、不补丁、不同步正文；`workspace-init` 只允许 seed 一次骨架。

按 `templates/REQUIREMENT_TEMPLATE.md` 的结构输出。**强制部分**：

- **TL;DR**：一句话/一段话说清楚做什么、为谁、为什么现在做。读完这一段读者就能判断"是不是他要找的东西"。
- **范围**：In scope / Out of scope（non-goals）必须显式列出。

**可省部分**（按 workspace 实际情况决定深度）：

- **约束与已定决策**：硬约束 + 已在 `decisions/` 里详细记录的关键拍板
- **开放问题**：还没想清楚但会影响交付的；都想清楚了可整段删
- **详情**：自由区，无固定小标题，按 workspace 特点写

**与 `workspace-summary.md` 的边界**：

- `Requirement.md`：稳定需求共识正文
- `workspace-summary.md`：当前状态、导航与压缩摘要

**禁止**：

- ❌ 不要把 `context/clarifying-log.md` 或 `research/research-log.md` 的原文直接贴成正文——log 是历史，Requirement 是消化后的结论
- ❌ 不要重复 `.pmagent/current-state.json` 里的机器状态字段（phase / active_step / 优先级 / 状态）
- ❌ 不要写"为什么要做这个需求？{...}"这类模板化占位

**关键要求**：

- **所属项目链接**正确（相对路径指向 `projects/<project>/PROJECT.md`）
- **TL;DR** 精准——后续判断 workspace 复用靠它
- 同步更新 `workspace-summary.md` 的 CORE 区

### Step 6: 落盘与登记

- 写入 `workspaces/<workspace>/Requirement.md`
- 更新 `config/projects.json`：在对应 project 下添加 workspace 条目（含 `description`、`keywords`）
- **执行 `pmagent switch <project> <workspace>`**：切换隔离，排除其他项目/需求
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显完整路径，确认落盘位置

## 模板真相源

- Requirement 的唯一模板真相源：`../../../templates/REQUIREMENT_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名固定为 `Requirement.md`
- TL;DR 与 范围（in/out scope）为强制段落，不可省略
- 必须保证所属项目链接正确
- 必须保证 TL;DR 精准可复用
- 必须保证"关联材料"段的链接指向当前 workspace 的标准子目录
