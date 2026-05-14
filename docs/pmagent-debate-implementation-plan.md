# pmagent Debate 接入实施计划

## 文档定位

这份文档回答的是一个很具体的问题：

> **基于当前 pmagent 仓库的真实结构，Debate 机制第一版最应该怎么接，应该先做到什么程度，哪些地方先不要碰。**

它和 `docs/pmagent-debate-design.md` 的关系是：

- `pmagent-debate-design.md`：偏完整设计，讲总体边界、理想形态和长期方向。
- **本文**：偏当前仓库实施，强调“现在这个代码库最稳的接法”。

换句话说，本文不是重新发明一套 Debate 理论，而是把你提供的聊天记录共识，翻译成当前 pmagent 可以执行的实施计划。

---

## 1. 从聊天记录里收敛出来的稳定共识

结合 `2026-04-20-full-conversation-export.md`，当前已经比较稳定的结论有：

1. **Debate 是 step，不是 mode**
   - 它是一个观点深化步骤。
   - 不替代 `zero-to-one`、`conviction-forge`、`challenge-prd`。

2. **Debate 必须是独立 CLI 进程**
   - 不能绑定在当前 Agent 会话里同步执行。
   - 这样才能异步跑，并保持主流程可继续推进。

3. **双方都走 CLI 执行器调用**
   - 主会话不直接参与轮次生成。
   - 主 Agent 的角色是发起、读取、消费 synthesis，不是下场辩论。
   - 第一版优先调用 `codex exec` / `claude -p` 这类 CLI 执行面，而不是直接下沉到 provider SDK。

4. **默认不是“辩到共识为止”**
   - 正确的结束条件是：**固定轮数后输出结构化结果**。
   - 最重要的产出不是共识，而是：
     - 收敛点
     - 分歧点
     - 意外发现

5. **默认 3 次交互**
   - Round 0：独立起手
   - Round 1：交锋
   - Round 2：深入

6. **对立轴默认由主 Agent 在交互流里提议，不应让 CLI 自己承担默认提轴角色**
   - 更合理的是：**主 Agent 基于当前上下文提议候选轴，人确认或微调**。
   - 人的角色是判断者，不是从零生成者。

7. **Debate 的价值在暴露张力，不在替人做决策**
   - 人最后仍是裁判。
   - Debate 只负责把真正值得裁决的 fork 显性化。

8. **不为 Debate 额外开发自动级联修正系统**
   - Debate 在 PRD 之前时，它天然就是 PRD 输入。
   - Debate 在 PRD 之后时，沿用现有 maintenance 思路即可。

9. **第一版不做自动触发系统**
   - 只保留：
     - 人主动发起
     - Agent 在关键节点提示“这里可以开 Debate”

这些共识决定了 Debate 的第一版形态：**独立旁路，不改主 phase，不抢主流程。**

---

## 2. 结合当前仓库，Debate 最适合挂在哪里

从现有目录和代码职责看，Debate 最适合沿着“独立 artifact 通道 + 状态投影”的方式接入。

### 2.1 当前仓库里的关键接入点

- `src/pmagent/cli.py`
  - 顶层 CLI 路由入口。
  - 适合新增 `pmagent debate ...` 子命令组。

- `src/pmagent/current_state.py`
  - 负责 `current-state.json` 快照和前门状态的底层数据来源。
  - 适合新增 debate snapshot。

- `src/pmagent/cli_routing.py`
  - 负责 `status / review / next` 的展示逻辑。
  - 适合把“有已完成但未消费的 debate”显示出来。

- `src/pmagent/observation/summary_protocol.py`
  - 当前 `workspace-summary.md` 的协议层。
  - 可以在后续阶段承接 Debate 可视化，但**第一版不建议先改 marker 协议**。

- `src/pmagent/skills/README.md`
  - 当前 Step 地图里没有 Debate。
  - 适合补上 `skills/steps/debate/skill.md`，把 Debate 正式纳入 step 体系。

- `src/pmagent/observation/maintenance.py`
  - 当前已经有“发现变化 → 人裁决 → 维护 canonical artifact”的治理思路。
  - Debate 在 PRD 之后的回流，应优先复用这条治理思路，而不是发明全新闭环。

### 2.2 为什么不建议把 Debate 做成新 phase

当前 pmagent 的主 phase 仍然围绕：

- clarifying
- researching
- delivery
- maintaining / observation 治理

如果 Debate 升成 phase，会立刻带来这些代价：

- phase 切换规则要扩展
- readiness 体系要新增 debate readiness
- `status / route / review / next` 都要重解释

而根据聊天记录，Debate 的本质不是“新主线阶段”，而是“观点深化旁路”。

因此最稳的接法是：

> **Debate 不改 phase，只产出独立文件，再把它的状态投影回 current-state / status / review。**

---

## 3. 第一版产品形态建议

### 3.1 一个 topic 就是一场完整 debate

推荐模型：

- 一个 debate run = 一个 topic
- 一个 topic = 一次完整的 3 次交互
- topic 之间不共享对话历史，只共享同一个 workspace 上下文

这样做的好处：

1. 和 pmagent 当前的文件协议风格一致。
2. 不需要维护跨 topic 运行态。
3. 多 topic 可天然并存。
4. 即使 topic 独立，只要底层 CLI 所绑定的模型服务支持 prompt caching，相同的 context 前缀仍然可以降低成本。

### 3.2 第一版只做“启动 → 落盘 → 汇总 → 消费”

第一版不建议一开始就做太多高级能力，例如：

- 自动触发
- 自动二次辩论
- pause / resume
- 中途 inject
- 自动级联修正
- summary 协议大改

第一版最小闭环应该是：

1. 生成候选对立轴
2. 人确认轴
3. 启动 debate
4. 写出 round 文件
5. 写出 synthesis
6. 在 status 中显示“有待消费 debate”

---

## 4. 执行器策略：第一版先走 CLI as executor

这是当前讨论里最新锁定的实现取向。

当前环境已经具备：

- `codex`
- `claude`
- 这两类 CLI 的非交互或可程序化调用能力
- 主 Agent 可以通过 Bash 在后台拉起独立进程

因此，第一版最稳的做法是：

### 4.1 先把 CLI 当作模型执行器

优先支持：

- `codex exec`
- `claude -p`
- 后续按需补其它 CLI 执行器

好处：

- 不需要第一版就做 provider SDK 抽象
- 能尽快验证 Debate 的核心机制
- 仍然保留独立进程、落盘协议、异步回流这些关键能力
- 与“先在某一个 CLI 里把机制跑通”的目标一致

### 4.2 原生 provider API 放到第二阶段

例如：

- 原生 Anthropic
- OpenAI / OpenRouter / Gemini 等直连
- 更通用的 provider 抽象与 cost 统计

不需要第一版就把 provider 抽象做到最大。

第一版的目标不是 provider 框架优雅，而是 **Debate 真正能跑起来**。

---

## 5. 推荐的命令面设计

我建议第一版先做 4 个核心命令，并明确：

- **axis 候选默认由主 Agent 在交互流里提出**
- CLI 不再承担默认提轴入口

### 5.1 `pmagent debate start`

用途：正式启动一场 debate。

前提：

- 主 Agent 已在交互流里提议候选轴
- 用户已明确选定一个 axis

示例：

```bash
pmagent debate start \
  --workspace <ws> \
  --topic "mvp-vs-complete-experience" \
  --thesis "Should we prioritize validation speed or product completeness?" \
  --axis "validation speed vs product completeness" \
  --defender-exec codex \
  --attacker-exec claude
```

建议：

- 如果没传 `--axis`，直接报错并提示先由主 Agent 提轴、让用户选轴
- 保持 CLI-first，不做隐式交互问答

### 5.2 `pmagent debate status`

用途：查看当前 workspace 下 debate 概况，或者查看单个 topic 状态。

示例：

```bash
pmagent debate status --workspace <ws>
pmagent debate status --workspace <ws> --topic <topic>
```

### 5.3 `pmagent debate show`

用途：查看某个 topic 的轮次内容或 synthesis。

示例：

```bash
pmagent debate show --workspace <ws> --topic <topic>
pmagent debate show --workspace <ws> --topic <topic> --round 1
```

### 5.4 可选：`pmagent debate mark-reviewed`

用途：当人或主 Agent 已消费 synthesis 后，显式标记为已读。

这不是 MVP 必需，但如果后面需要稳定显示“completed but awaiting review”，最终会需要一个消费标记。

---

## 6. 推荐的落盘协议

建议直接落在当前 workspace 的 `context/` 下：

```text
workspaces/<workspace>/
  context/
    debates/
      <topic>/
        run.json
        axis.json
        status.json
        context-manifest.json
        round-0-defender.md
        round-0-attacker.md
        round-1-defender.md
        round-1-attacker.md
        round-2-defender.md
        round-2-attacker.md
        synthesis.md
        review.json
```

### 文件职责建议

- `run.json`
  - topic、thesis、workspace、created_at、executor、round_count

- `axis.json`
  - 最终选定的对立轴
  - 可附带主 Agent 在交互流里提议的候选轴

- `status.json`
  - `queued / running / completed / failed`
  - 当前轮次
  - started_at / completed_at
  - error 信息

- `context-manifest.json`
  - 本次 debate 读取了哪些文件
  - 用于回溯“这场 debate 基于什么上下文”

- `round-*.md`
  - 每轮原始输出

- `synthesis.md`
  - 给主 Agent 和人消费的结构化结论

- `review.json`
  - 可选；记录 consumed_at / reviewed_by

### `synthesis.md` 建议结构

```markdown
# Debate Synthesis: <topic>

## Thesis

## Chosen Axis

## Convergence

## Core Disagreements

## Unexpected Findings

## What This Changes
- 对 Requirement / Strategy / PRD 的潜在影响
- 需要人判断的点

## Recommended Next Action
- keep current direction
- revise strategy
- update PRD
- open maintenance draft
- run a narrower follow-up debate
```

这里最重要的不是总结“谁赢了”，而是告诉主流程：

> **这场 Debate 之后，下一步应该怎样消费这些结论。**

---

## 7. Prompt 工程：第一版该怎么定

### 7.1 不做简单正反方，做“优化目标对立”

坏方案：

- A 支持 X
- B 反对 X

这很容易变成两份平行分析报告。

更好的方案是：

- Defender：优先维护当前方向在某个目标下的合理性
- Attacker：优先从另一个目标下攻击当前方向的代价和盲区

典型对立轴：

- validation speed vs product completeness
- short-term gain vs long-term compounding
- user experience vs engineering simplicity
- flexibility vs present simplicity

### 7.2 推荐的 3 次交互结构

#### Round 0：独立起手

双方只看：

- thesis
- chosen axis
- workspace context

双方**不看对方发言**。

目标：先暴露各自最自然、最原生的关注点，避免一开始就被对方框住。

#### Round 1：交锋

双方读取对方 Round 0，然后开始反驳。

目标：指出对方论据里最弱的一环，以及它带来的真实代价。

#### Round 2：深入

双方不再铺太多新战线，而是聚焦最核心分歧。

目标：把真正值得人裁决的 fork 压缩出来。

### 7.3 第一版就应该加的反和稀泥约束

建议直接写进 hard constraints：

- 不得使用“折中一下”“两边都有道理”“具体情况具体分析”作为逃生口
- 每轮最多 3 个核心论点
- 必须回应对方上一轮最强的一条主张
- 每轮最后必须给出一句明确单主张结论

这样做不是为了制造戏剧冲突，而是为了压制模型默认的礼貌性收敛。

---

## 8. 状态接入：第一版先接 current-state，不先动 summary 协议

这是当前项目里最应该谨慎的一点。

当前 `workspace-summary.md` 的 marker 协议比较硬：

- CORE
- OBSERVATION

如果现在直接增加第三个 Debate marker，会带来：

- marker 校验逻辑修改
- 已有 summary 的迁移问题
- 本来独立的功能变成 summary 协议升级

### 8.1 更稳的第一版做法

先做：

- `current_state.py` 扫描 `context/debates/*/status.json`
- 在 `current-state.json` 里新增 `debates` 快照
- `cli_routing.py` 在 `pmagent status` 中增加 debate 概况

例如：

```json
"debates": {
  "active": 1,
  "completed_awaiting_review": 1,
  "latest_topic": "mvp-vs-complete-experience"
}
```

### 8.2 `status / review / next` 的建议集成方式

#### `status`

展示：

- running count
- completed awaiting review count
- latest topic

#### `review`

如果存在已完成未消费的 debate，把 synthesis 变成一个 review 入口。

#### `next`

如果当前 workspace 有已完成但未消费的 debate，给出：

- `pmagent debate show --workspace <ws> --topic <topic>`
- 或提示“读取 synthesis 后决定是否修订 strategy / PRD”

这条路线能让 Debate 自然进入前门命令体系，而不需要发明一条新的主链路。

---

## 9. 与现有 workflow 的接合点

### 9.1 关键节点提示 Debate 可用性

第一版只做“提示”，不做自动触发。

推荐落点：

- Strategy 确认前
- PRD challenge 前
- 重大 decision 落盘前

可能涉及：

- `skills/modes/zero-to-one/skill.md`
- `skills/modes/conviction-forge/skill.md`
- 新增 `skills/steps/debate/skill.md`
- `skills/README.md`

目标不是让系统自动判断“什么时候必须辩论”，而是：

> **在最可能需要 Debate 的节点，明确告诉用户和 Agent：这里可以开一场 Debate。**

### 9.2 PRD 之后的回流不新造机制

如果 Debate 发生在 delivery 之后，建议坚持这个处理原则：

- Debate 只产出 synthesis
- 人裁决是否需要改 PRD
- 如需修改，沿用 maintenance / canonical artifact 更新思路处理

也就是说：

- Debate = 新信号源
- maintenance = 现有治理面

这和当前仓库风格是一致的。

---

## 10. 建议的代码改动清单

### 10.1 P0：必须有，才能跑通闭环

#### 新增

- `src/pmagent/debate/__init__.py`
- `src/pmagent/debate/cli.py`
- `src/pmagent/debate/orchestrator.py`
- `src/pmagent/debate/executors.py`
- `src/pmagent/debate/storage.py`
- `src/pmagent/debate/synthesis.py`
- `src/pmagent/skills/steps/debate/skill.md`

#### 修改

- `src/pmagent/cli.py`
  - 注册 `debate` 子命令组

- `src/pmagent/current_state.py`
  - 增加 debate snapshot

- `src/pmagent/cli_routing.py`
  - 在 `status` detail lines 中增加 debate 状态
  - 在 `review / next` 中接入“awaiting review”信号

- `src/pmagent/skills/README.md`
  - 把 Debate 正式列入 step 地图

### 10.2 P1：建议尽快补上，但不是首发阻塞

- `src/pmagent/scaffold/README.md`
  - 说明 `context/debates/` 的用途

- `src/pmagent/templates/`
  - 增加 defender / attacker / synthesis prompt 模板

- `src/pmagent/cli_workspace.py`
  - 视情况为新 workspace 预留 debates 目录；或者继续按需惰性创建

### 10.3 P2：跑通后再做

- `workspace-summary.md` 的 Debate 展示
- reviewed / consumed 标记闭环
- 原生 Anthropic / OpenAI provider 接入
- 更复杂的 environment-based executor activation

---

## 11. 建议的 MVP 切片

如果按当前仓库现实来排顺序，我建议这样切：

### MVP-1：先跑通一场 Debate

目标：

- `debate start`
- 落 round 文件
- 生成 synthesis

此阶段先不接 `status / review / next`。

### MVP-2：接入前门状态面

目标：

- `current-state.json` 出现 debate snapshot
- `pmagent status` 能看到 awaiting review

### MVP-3：接入 step / workflow 文档

目标：

- Debate 出现在 `skills/README.md`
- 关键节点提示规则落到 skill 合同中

### MVP-4：治理回流细化

目标：

- 明确 synthesis 如何指向 strategy / PRD / maintenance
- 再考虑 reviewed 标记和 summary 展示

这个顺序的好处是：

- 每一步都能独立验证
- 不会一上来就同时改 phase、summary、原生 provider 三大系统
- 和 pmagent 当前“小步接入”的风格一致

---

## 12. 第一版验收标准

第一版不要求辩论质量已经最优，但至少要满足这些可验证条件：

1. 可以基于一个 workspace 生成候选对立轴。
2. 可以基于已确认 axis 跑完 3 次交互。
3. 每轮输出都会实时落盘到 topic 目录。
4. 最终一定生成 `synthesis.md`。
5. `current-state.json` 能反映 debate 是否存在待消费结果。
6. `pmagent status` 至少能显示一条 debate 状态信号。
7. 不需要改 phase 就能使用 Debate。
8. PRD 之后的 debate 结果仍可被人工消费并回流，不强制自动改文档。

---

## 13. 两个最关键的项目判断

### 判断 A：第一版不要为了“理想 provider 架构”拖慢落地

当前我们已经明确：**先用 CLI 当执行器**，而不是第一版先把 provider SDK 全部收编。

所以更合理的是：

- 先基于 `codex` / `claude` 这类 CLI 把 Debate 跑起来
- 先把 orchestrator、round 协议、落盘协议、回流协议打稳
- 以后真要补原生 SDK，再补

### 判断 B：第一版不要为了“summary 很漂亮”先改大协议

当前 summary marker 协议比较硬。

所以第一版更合理的是：

- 先把 Debate 接进 `current-state.json`
- 再通过 `status / review / next` 暴露出来
- 等功能跑通后，再决定 summary 怎么演进

---

## 14. 一句话结论

**如果按当前仓库现实来做，Debate 最合理的接法不是“新增一个大 mode”，而是“新增一个独立 CLI artifact 通道，并把它的状态投影回 current-state / status / review”。**

这条路既保留了聊天记录里已经达成的设计共识，也尽量少碰当前 pmagent 已经成型的 phase、summary 和 maintenance 结构。
