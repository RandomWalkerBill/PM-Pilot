# pmagent Debate × Hooks 主流程嵌入设计

## 文档定位

这份文档只回答一个问题：

> **Debate 机制除了靠 skill / AGENTS.md 的软提醒之外，还能如何借助 hooks 更强地嵌入主流程？**

它不讨论 Debate 的 round 执行内核，也不替代：

- `docs/pmagent-debate-final-summary.md`
- `docs/pmagent-hooks-enforcement-design.md`
- `docs/pmagent-workflow-with-hooks.md`

本文聚焦的是：

- Debate 该在主流程的哪些节点出现
- 哪些地方可以只做 soft reminder
- 哪些地方可以升级成 hard gate
- 当前现有 hook 模块可以如何复用

---

## 一句话结论

> **Debate 的执行过程本身不应该塞进 hooks；但 Debate 与主流程的连接点，非常适合借 hooks 做成“可见性增强 + review 门禁 + canonical 文档边界保护 + 消费闭环 + 结论结构校验”。**

换句话说：

- **执行内核**：继续留在 `pmagent debate` orchestrator
- **主流程嵌入**：交给 hooks

---

## 1. Debate 实际应该出现在哪些阶段

这里按当前最新共识锁定。

## 1.1 需求澄清与调研之间

这是 Debate 的第一个关键时机。

典型信号：

- 当前 phase = `clarifying`
- readiness 已接近 / 达到 researching
- 用户明确说“可以往 research 走了”
- 或当前方向已经形成初步共识，但还不够稳

这里 Debate 的作用是：

- 在真正进入 research 之前，先打一次方向上的核心张力
- 为后续 research / strategy 输入更好的问题框架

## 1.2 PRD 生成之后

这是第二个关键时机。

典型信号：

- 已存在 `prd/current.md`
- 或刚执行完 `pmagent prd init-draft`
- 下一步通常会走 challenge / review / refinement

这里 Debate 的作用是：

- 不再只是普通 challenge
- 而是对某个关键 fork 开一场真正的对打

## 1.3 高影响 decision 落盘前

这是第三个关键时机。

典型信号：

- 用户准备把某个方向性判断写入 `decisions/`
- 该 decision 会直接影响：
  - strategy
  - 范围取舍
  - PRD 主方向
  - 资源分配

这里 Debate 的作用是：

- 避免高影响 decision 只基于单一路径推导直接落盘
- 在落 decision 前，先显式暴露最关键分歧

## 1.4 用户明确表达犹豫时

这是第四个关键时机。

典型信号：

- “我不太确定”
- “这个方向对不对”
- “我担心另一条路可能更合理”
- “要不要再看看别的角度”

这里 Debate 的作用是：

- 作为一个被明确提议出来的工具
- 让“犹豫”进入结构化深化，而不是继续随口来回聊

---

## 2. Debate 不该靠 hooks 做什么

为了避免过度设计，这些事**不要**交给 hooks：

1. **不要让 hooks 自动启动 Debate**
   - Debate 是否要开，仍然应由人决定。

2. **不要让 hooks 执行 Round 0 / 1 / 2**
   - hooks 是短时事件；Debate 是长时状态机。

3. **不要让 hooks 自动选 axis**
   - axis 仍然是“AI 提议 + 人确认”。

4. **不要让 hooks 自动决定 extend / stop**
   - 这是高阶判断，应由人裁决。

5. **不要让 hooks 直接改 PRD / Requirement / decisions**
   - hooks 只负责 gate / inject / validate，不负责 mutation。

这条边界很重要：

> hooks 负责“把 Debate 更强地嵌进主流程”，但不负责“替 Debate 做执行内核”。  

---

## 3. Debate × Hooks 的五类能力

我建议把 Debate 的 hooks 作用拆成五类：

1. **可见性增强**
2. **机会提示**
3. **review 门禁**
4. **canonical 文档边界保护**
5. **消费闭环与输出校验**

下面分别展开。

---

## 4. 可见性增强：让 Debate 从后台任务变成主流程可见状态

## 4.1 SessionStart：注入 pending synthesis

### 推荐 hook
- `session_bootstrap`

### 做法

在会话开始时：

- 读取 active workspace
- 扫描：
  - `context/debates/*/signal.json`
  - 或更推荐：`.pmagent/current-state.json` 里的 `debates` 快照

如果存在：

- `completed`
- `action_needed = review_synthesis`

就把它作为上下文块注入。

### 预期效果

主 Agent 一开场就能知道：

- 现在不只是有 observation backlog
- 还有 debate synthesis backlog

### 注入示例

```text
## Pending Debate Syntheses

- topic: mvp-vs-complete-experience
- completed_at: ...
- synthesis: context/debates/.../synthesis.md
- action_needed: review_synthesis
```

### 强度
- **非阻断**
- 但属于强可见性注入

---

## 4.2 UserPromptSubmit：每轮 surface debate 状态

### 推荐 hook
- `state_surface`

### 做法

在每一轮用户发话前：

- 读取 `.pmagent/current-state.json`
- 检查：
  - 是否有 `debate_review.completed_awaiting_review_count > 0`

如果有，就注入一段提醒。

### 注入示例

```text
WARNING debate_visibility_gate:
有 1 份 debate synthesis 待裁决。
建议先执行：
pmagent debate show --workspace <ws> --topic <topic>
```

### 强度
- **默认非阻断**
- 但可反复 surface

---

## 5. 机会提示：不只软提醒，但也不直接自动触发

这里对应你明确指定的四个阶段。

## 5.1 澄清 → 调研之间

### 推荐 hook
- `state_surface`
- 必要时配合 `session_bootstrap`

### 推荐触发条件

满足任意一个即可提示：

- `phase == clarifying`
- readiness 已给出 researching 的 transition recommendation
- 用户明确表达“可以往 research 推了”

### 注入内容

```text
Debate opportunity:
当前已接近从 clarifying 进入 researching。
如果你觉得方向仍有核心张力，可在进入 research 前先开一场 debate。
```

### 强度
- **soft reminder**

### 是否建议 hard gate
- **默认不建议**
- 因为不是每个 workspace 都必须在这里开 debate

---

## 5.2 PRD 生成之后

### 推荐 hook
- `PostToolUse`（Bash）
- `state_surface`

### 推荐触发条件

例如命中：

- `pmagent prd init-draft`
- 或 `artifacts.prd.status in {"draft","active"}`
- 且最近尚未出现 debate review / decline 标记

### 做法

在 PRD 刚生成之后：

- 通过 `PostToolUse:Bash` 注入“可开 Debate”的 system-reminder
- 后续在 `UserPromptSubmit` 持续保留该提示，直到：
  - 用户明确跳过
  - 或 debate 已启动

### 注入内容

```text
Debate opportunity:
PRD 已生成。进入普通 challenge 前，可以先针对某个关键子议题开一场 debate。
```

### 强度
- **soft reminder**

### 是否建议 hard gate
- **默认不建议**
- 因为不是每份 PRD 都要 debate

---

## 5.3 高影响 decision 落盘前

这是最容易做成“强一点但仍克制”的地方。

### 推荐 hook
- `state_surface`
- 后续可选 `pre_write_guard`
- 后续可选 `pre_bash_guard`

### 推荐触发条件

MVP 阶段不建议做高阶语义自动判断“这是不是高影响 decision”。  
这一节只在未来有**明确状态源**时才建议上 hook。

例如未来可以依赖：

- `active_step == high-impact-decision`
- 或 `pending_user_decision == decision-record`
- 或用户明确说“我要把这个方向定下来”

### 做法

#### 当前阶段
- 保留为概念性时机，但不在 hook 层落地

#### 第二阶段
- 如果主流程后来补出了明确状态或显式命令，再在这里挂提示或 gate

### 强度
- **MVP 不落 hook**
- 后续可升级为 soft / 半硬 gate

### 说明

高影响 decision 的难点不在 hook 技术，而在“是否已有稳定 state 信号”。  
如果没有，不要让 hook 自己猜。

---

## 5.4 用户明确表达犹豫时

### 推荐 hook
- `UserPromptSubmit`

### 推荐触发方式

读取当前用户 prompt（或 transcript 最近一条 user turn），匹配犹豫词：

- 不太确定
- 这个方向对不对
- 犹豫
- 拿不准
- 有没有另一种可能

### 做法

匹配到后，注入一条简短提示：

```text
Debate opportunity:
用户明确表达了方向性犹豫。这里可以建议开启一场 debate，而不是继续单线程推进。
```

### 强度
- **只做 soft reminder**
- **绝不阻断**

### 为什么

因为“表达犹豫”是最典型的高阶语义信号，适合提示，不适合硬拦。

### MVP 决策

**这一条 hook 级词匹配不进入 MVP。**

理由：

- 信噪比不稳定
- 在正常 PM 对话里误触发率会偏高
- 容易把每轮 `UserPromptSubmit` 变成噪音源

MVP 阶段保留：

- 主文档里的“这是 Debate 应出现的时机”
- 主 Agent / skill 合同里的人工提示

把 hook 级词匹配留到第二期。

---

## 6. review 门禁：不只是提醒，而是让 Debate review 进入稳定流转规则

这是 Debate hooks 化最有价值的部分。

## 6.1 推荐新增的 state 表达

建议在 `.pmagent/current-state.json` 中加入两层 Debate 相关状态：

```json
"debates": {
  "active_count": 0,
  "completed_awaiting_review_count": 1,
  "latest_topic": "mvp-vs-complete-experience"
},
"debate_review": {
  "active": true,
  "awaiting_review_topics": ["mvp-vs-complete-experience"],
  "completed_awaiting_review_count": 1
}
```

这样做的目的，是让 Debate review **不要占用** `active_step` / `pending_user_decision` 这类单槽位字段，避免和 observation 的 `candidate-review` 冲突。

也就是说：

- observation 继续用：
  - `candidate_review`
- debate 另走：
  - `debate_review`

两者是并行字段，而不是互相覆盖。

### owner 绑定（必须明确）

`debate_review` 不能悬空，必须有 owner。

当前建议是：

- `pmagent debate review --workspace <ws> --topic <slug>`
  - 负责把：
    - `debate_review.active = true`
    - `debate_review.awaiting_review_topics += [<slug>]`
    - `debate_review.completed_awaiting_review_count` 同步更新
    写入 `current-state.json`
- `pmagent debate resolve --workspace <ws> --topic <slug> --accepted|--rejected|--deferred`
  - 负责清理 `debate_review` 中对应 topic
  - 负责写 `review.json`
  - 负责把这场 Debate 标记为已处理 / deferred

没有这个 owner，所有依赖 `debate_review` 的 hook 都无法落地。

---

## 6.2 PreToolUse:Bash：拦截下游推进动作（第二期）

### 推荐 hook
- `pre_bash_guard`

### 建议新增 gate
- `debate_review_gate`

### 现状判断

这一条**不进入 MVP**。

原因：

- 当前文档里还没有稳定的 `blocking debate` 来源
- 如果先上硬 gate，很容易把用户困住
- 目前更合理的是：先靠 `state_surface` 反复提醒，再观察真实使用

### 第二期前提

只有在以下任一条件成立时，才建议上这条 gate：

1. Debate 启动时支持显式 `--blocking`
2. 某些触发点能稳定自动打标为 blocking
3. 明确设计了用户逃生口，例如：
   - `pmagent debate resolve --deferred`

### 未来适合拦哪些命令

一旦启用，这条 gate 只建议拦**下游推进性命令**，不要拦一切命令。

优先考虑：

- `pmagent export`
- `pmagent workspace-close`
- `pmagent observe apply-maintenance`
- 某些明确会推进到下游交付的动作

如果未来某个 debate 被显式标记为“PRD 前 blocking debate”，还可以考虑：

- `pmagent prd init-draft`

### 阻断提示示例

```text
blocked by debate_review_gate:
当前有 blocking debate synthesis 尚未裁决。
请先 review synthesis，再决定是否继续推进主流程。
```

### 强度
- **第二期硬 gate**

---

## 7. canonical 文档边界保护：防止 debate 未消费前直接改 PRD/Requirement

这是第二个最值得做成 hard gate 的地方。

## 7.1 PreToolUse:Edit/Write

### 推荐 hook
- `pre_write_guard`

### 建议新增 gate
- `debate_boundary_gate`

### 阻断条件

当：

- `debate_review.completed_awaiting_review_count > 0`

且目标路径命中：

- `workspaces/<ws>/prd/**`
- `workspaces/<ws>/Requirement.md`

则阻断。

### 为什么拦这两个

因为它们是最核心的 canonical 主文档。

在 Debate 结论还没被裁决前，直接改它们最容易把“背景信号”误当成“正式结论”。

### 为什么不默认拦 `decisions/` / `strategy/`

因为这些路径恰恰可能是“消费 synthesis”最合理的出口：

- `decisions/`：把 debate 的裁决固化
- `strategy/`：把 Debate 结果吸收为方向修订

所以：

- **强拦**：PRD / Requirement
- **默认放行**：decisions / strategy / maintenance draft

### 阻断提示示例

```text
blocked by debate_boundary_gate:
当前存在待裁决的 debate synthesis，不能在未消费 Debate 结论前直接修改 PRD / Requirement。
请先读取 synthesis，形成裁决，再通过 decision / strategy / maintenance 路径回流。
```

### 强度
- **硬 gate**

### MVP 说明

这是 Debate hooks 化里**唯一建议在 MVP 就落地的硬 gate**。

原因：

- 它只保护最核心的 canonical 文档
- 不需要 blocking debate 概念也能成立
- 出错面小

---

## 8. 消费闭环：当主流程真的消化了 Debate，要把它从 backlog 里摘掉

## 8.1 PostToolUse：自动标记 consumed

### 推荐 hook
- `post_mutation_check`

### 建议新增能力
- `debate_consumption_mark`

### 推荐判定逻辑

如果存在：

- `debate_review.completed_awaiting_review_count > 0`

并且随后发生了这些动作之一：

- 写入 `decisions/`
- 写入 `strategy/`
- 执行 `pmagent observe draft-maintenance`
- 执行 `pmagent observe apply-maintenance`

就可认为：

> Debate 已被主流程消费，而不只是“看过”。

### 这时可以做什么

自动写：

- `review.json`
- 或更新 `current-state.json.debate_review` / `debates` 中的 consumed 信息

推荐 `review.json` 路径：

```text
workspaces/<workspace>/context/debates/<topic>/review.json
```

最小 schema 可先定为：

```json
{
  "topic": "<slug>",
  "status": "accepted|rejected|deferred",
  "resolved_at": "...",
  "resolved_by": "agent|user",
  "notes": ""
}
```

### 强度
- **非阻断**
- 但属于强闭环能力

---

## 9. 输出结构校验：主 Agent 一旦引用 Debate，就不能只做低信息密度复述

## 9.1 Stop：强制 Debate 结论结构

### 推荐 hook
- `response_validator`

### 建议新增 gate
- `debate_visibility_gate`
- 或 `debate_summary_gate`

### 触发条件

如果最近上下文中出现：

- `synthesis.md`
- debate `action_needed=review_synthesis`
- 或 `current-state.debates`

并且主 Agent 本轮在回答 Debate 结果或据此给建议，则要求它显式输出：

- 收敛点
- 分歧点
- 意外发现
- 下一步建议

### 价值

防止主 Agent 在读完 synthesis 后只回一句：

- “这个 debate 很有价值，建议你再想想”

这样的低信息密度内容。

### 强度
- **可以做成硬 gate**
- 但建议放第二阶段

---

## 10. Debate × Hooks 推荐落地顺序

## P0：先做，可见性和最关键边界

1. `SessionStart` 注入 pending debate synthesis
2. `UserPromptSubmit` surface debate backlog
3. `PreWriteGuard` 在 `debate_review.completed_awaiting_review_count > 0` 时保护 PRD / Requirement

## P1：再做，真正进入流转

4. `PostToolUse` 自动标记 debate consumed
5. `PreToolUse:Bash` 的 `debate_review_gate`

## P2：最后做，质量增强

6. `Stop` 阶段的 debate 总结结构校验
7. 高影响 decision 的显式状态信号与 gate
8. 用户犹豫词匹配

---

## 11. Debate × Hooks 的最终建议

### 可以由 hooks 强化的能力

- synthesis backlog 可见性
- canonical 文档边界保护
- consumed 闭环
- 结果结构校验
- debate review 门禁（第二期）

其中真正适合做成 **hard gate** 的，当前主要是：

- canonical 文档边界保护
- 结果结构校验（第二期）
- debate review 门禁（第二期）

其中 MVP 阶段建议先只落：

- canonical 文档边界保护

### 仍然保持软约束的

- 是否要开 debate
- 澄清 → 调研之间是否一定要开
- PRD 后是否一定要开
- 高影响 decision 前是否一定要开
- 用户犹豫时是否一定要开
- MVP 里的 debate review 提醒

### 原因

因为这些动作仍然是：

- 高阶判断
- 需要人的裁决
- 不适合被 hooks 直接替代

---

## 12. 一句话结论

**Debate 机制不应该只停留在“关键节点 soft reminder”，完全可以借 hooks 更强地嵌进主流程；但 hooks 该增强的是“可见性、review 门禁、文档边界、消费闭环、结论结构”，而不是把 Debate 的执行状态机本身塞进 hooks。**
