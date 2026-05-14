# pmagent Debate 五个关键对齐点汇总

## 文档定位

这份文档的目标不是重新展开完整设计，而是把当前最需要对齐的 5 个问题单独收束出来，方便快速评审：

1. 如何调用其他模型
2. 调用过程中各自的 prompt 怎么设计
3. 每一个 round 的结论落在哪里
4. 调用完成后结论应该怎么输出
5. Debate 应该在哪个阶段提供给用户，以及结果如何异步插入主流程

本文依据：

- 你提供的 `2026-04-20-full-conversation-export.md`
- `docs/pmagent-debate-design.md`
- `docs/pmagent-debate-implementation-plan.md`

如果三者有轻微冲突，**以“聊天记录里后期确认过的结论 + 当前仓库最稳的实现路径”为准**。

---

## 一页结论

当前更合理的总方案是：

> **Debate 做成独立 CLI 异步旁路。主 Agent 在关键节点提示 Debate 可用，由用户主动发起；CLI 后台拉起一个 orchestrator，再由 orchestrator 调用 `codex exec` / `claude -p` 这类 CLI 执行器跑 3 轮结构化辩论；每轮独立落盘到 `context/debates/<topic>/`；结束后生成 `synthesis.md`，再通过 `current-state / status / review / next` 回流主流程。**

一句话拆开就是：

- **调用方式**：独立 CLI + CLI 执行器优先，不先做原生 provider API
- **prompt**：优化目标对立，不做简单正反方
- **round 落盘**：`context/debates/<topic>/round-N-{pro,con}.md`
- **最终输出**：结构化 `synthesis.md`
- **提供时机**：关键节点 soft reminder + 用户主动触发
- **异步插入**：后台运行，主流程通过状态面自然感知，不打断当前链路

---

## 1. 如何调用其他模型？

## 当前建议

**正式方案：独立 CLI 进程 + CLI 执行器。**

也就是：

- 主 Agent 不亲自当辩手
- 主 Agent 只负责：
  - 在合适时机发起 debate
  - 后台拉起 `pmagent debate start ...`
  - 后续读 `synthesis.md`
- 真正的辩手是 Debate CLI 进程里调用的两个执行器，例如：
  - `claude -p ...`
  - `codex exec ...`

### 推荐调用链路

```text
主 Agent（Claude Code / Codex）
  └─ Bash(run_in_background=true)
      └─ pmagent debate start ...
          └─ Python orchestrator
              ├─ Executor A（Defender）
              └─ Executor B（Attacker）
```

### 为什么现在不选 subagent？

这里需要修正一个前提：

- **如果**宿主里的 subagent 只能继承同一种模型，那它确实会退化成“同模型 + 不同 prompt”
- **但如果**宿主支持给 subagent 绑定不同模型 / API，那它是可以做 Debate 的

所以现在不选 subagent，**不是因为它绝对做不到**，而是因为当前阶段我们更倾向于：

- 直接把 `codex` / `claude` CLI 当作可程序化调用的执行面
- 先把 Debate 的文件协议、轮次协议、回流协议跑通
- 暂时不把第一版实现绑定在宿主内部的 subagent 机制上

换句话说，当前排除的是：

- **宿主内 orchestrator**

而不是：

- **宿主 CLI 本身**

Debate 真正想得到的是：

- 不同模型
- 不同盲区
- 不同 RLHF 倾向
- 不同默认关注点

所以：

- **subagent** 解决的是“宿主内部的 agent 分工”
- **CLI 执行器** 解决的是“可程序化调用不同模型的外部执行面”

### subagent 还值不值得用？

值，尤其适合做：

- prototype
- prompt 验证
- 宿主内体验实验版

只是当前这版我们先不把它定义成正式实现面。

### 执行器第一版怎么收敛？

结合当前仓库，第一版建议：

- **先走 CLI as executor**
  - `codex exec`
  - `claude -p`
  - 后续如有需要，再加其它 CLI 执行器
- 第二阶段再补：
  - 原生 provider API
  - 统一 provider 抽象
  - token / cost 的更精细统计

原因：

- 你当前已经明确：**先用 CLI 当执行器**
- 本机已有：
  - `codex`
  - `claude`
- 这两类 CLI 都支持非交互调用或可程序化启动
- 先跑通 Debate，比先把 provider SDK 抽象做满更重要

---

## 2. 调用过程中各自的 prompt 怎么设计？

## 当前建议

**不是简单正反方，而是“优化目标对立”。**

### 不建议的做法

坏方案：

- A：支持 X
- B：反对 X

这种方式的问题是：

- 很容易变成两篇平行分析
- 不一定真的交锋
- 很容易和稀泥

### 建议的做法

好方案：

- Defender：优先维护当前方向在某个目标下的合理性
- Attacker：优先揭示当前方向在另一个目标下的代价和盲区

例如常见对立轴：

- validation speed vs product completeness
- short-term gain vs long-term compounding
- user experience vs engineering simplicity
- flexibility vs present simplicity

---

### 2.1 Prompt 启动前，先做“候选对立轴生成”

不是直接开辩，而是先：

1. 输入 thesis
2. 主 Agent 结合当前上下文提 2–3 组候选轴
3. 用户选择 / 微调 / 全部否掉重写

也就是说：

```text
thesis
  ↓
AI 提议候选轴
  ↓
人确认或修正
  ↓
正式进入 Debate
```

这是非常关键的一步，因为后面 3 轮是不是打在“对的张力上”，取决于这里。

---

### 2.2 Prompt 建议结构

#### A. 固定 system prompt

建议由四部分组成：

1. **项目上下文**
   - Requirement.md
   - 当前 strategy / research 摘要
   - workspace-summary 或 current-state 摘要
   - thesis
   - selected axis

2. **角色设定**
   - Defender：维护当前方向
   - Attacker：攻击当前方向

3. **硬性规则**
   - 禁止“取决于情况”
   - 禁止“两边都有道理”
   - 禁止“可以结合一下”
   - 每轮最多 3 个核心论点
   - 必须回应对方上一轮最强的一条主张
   - 最终必须给一句单主张结论

4. **输出格式约束**
   - 本轮核心主张
   - 对方最弱的一点
   - 反驳理由
   - 具体场景 / 证据
   - 一句话结论

#### B. 每轮追加 user prompt

每轮只追加：

- 对方上一轮内容
- 本轮任务

这样更利于 prompt caching，也更利于 orchestrator 管理历史。

---

### 2.3 推荐的 3 轮结构

#### Round 0：独立起手

- 双方只看 context / thesis / axis
- **互相看不到对方内容**

目的：

- 暴露原生视角
- 避免一开始就被对方叙事框住
- 提高“意外发现”概率

#### Round 1：交锋

- 双方看对方 Round 0
- 各自攻击对方最弱的一环

目的：

- 把“真正的第一层张力”打出来

#### Round 2：深入

- 双方看 Round 1
- 聚焦一个最无法调和的分歧点

目的：

- 给人留下最值得裁决的 fork

### 2.4 角色分配建议

当前更稳的建议是：

- `primary = Defender`
- `secondary = Attacker`

但这里的 primary / secondary 指的是 **执行器身份**，不是主 Agent 会话本身。

因为既然已经选择“独立 CLI + CLI 执行器”，那双方都应该是由 orchestrator 程序化调用。

---

## 3. 每一个 round 的结论落在哪里？

## 当前建议

**每轮单独落盘，统一放到当前 workspace 的 `context/debates/<topic>/` 下。**

### 不建议写到哪里

第一时间不建议写进：

- `decisions/`
- `strategy/`
- `prd/`

原因：

- round 结果本质上还是**上下文素材**
- 它还不是正式决策
- 真正该回流主流程的，是 synthesis 之后的人类裁决

---

### 推荐目录结构

```text
workspaces/<workspace>/
  context/
    debates/
      <YYYY-MM-DD>-<topic-slug>/
        config.json
        axis.json
        status.json
        signal.json
        context-manifest.json
        round-0-pro.md
        round-0-con.md
        round-1-pro.md
        round-1-con.md
        round-2-pro.md
        round-2-con.md
        synthesis.md
        review.json
        cost-log.json
```

### 文件职责建议

#### `config.json`
- thesis
- topic
- round count
- executor 选择
- 创建时间

#### `axis.json`
- 候选对立轴
- 最终选择的对立轴
- 是否经过人工改写

#### `status.json`
- queued / running / completed / failed
- 当前轮次
- started_at / completed_at

#### `round-N-{pro,con}.md`
- 保存每轮原始输出

#### `signal.json`
- 给主流程和宿主一个轻量通知

#### `synthesis.md`
- 最终正式产物

### 原则

> **round 文件是 context artifact，不是 canonical decision。**

也就是说，round 不直接改主流程文档，只为后续 synthesis 和人工裁决服务。

---

## 4. 调用完成后结论应该怎么输出？

## 当前建议

**完成后输出一份结构化 `synthesis.md`，它是主流程消费 Debate 的唯一正式入口。**

### 不建议的做法

不建议让主 Agent 在第一版中：

- 自己重新阅读全部 round 文件再总结
- 直接自动改 PRD
- 直接自动写 decisions
- 自动回写 Requirement

更稳的方式是：

1. Debate 进程自己生成 synthesis
2. 主 Agent / 用户读取 synthesis
3. 再决定后续是否写入：
   - decisions
   - strategy
   - PRD
   - maintenance

---

### 推荐的 synthesis 结构

```markdown
# Debate Synthesis: <topic>

## Thesis

## Chosen Axis

## Convergence
- 双方都认同的结论

## Core Divergences
- 双方无法说服对方的核心张力
- Defender 立场
- Attacker 立场
- 人需要裁决的判断

## Unexpected Findings
- 辩论中新浮现、原命题未覆盖的视角

## Acknowledgements / Adjustments
- 双方在哪些轮次修正过立场

## Quality Flags
- hedging
- repetition
- insufficient evidence

## Recommended Next Action
- keep current direction
- revise strategy
- update PRD
- open maintenance draft
- run narrower follow-up debate
```

### synthesis 的真正职责

不是回答：

- 谁赢了

而是回答：

- 哪些点是双方都承认的
- 哪些点是真正没打穿的
- 哪些点值得人来裁决
- 这会影响主流程的哪一步

所以 synthesis 是：

- 人看的正式结论
- 主流程消费 Debate 的唯一入口

---

## 5. Debate 应该在哪个阶段提供？结果如何异步插入主流程？

这个问题其实分成两半：

1. **什么时候提示 / 提供 Debate**
2. **跑完以后怎么回到主流程**

---

### 5.1 Debate 应该在哪个阶段提供？

## 当前建议

**不做自动触发，只做关键节点 soft reminder + 用户主动触发。**

### 推荐时机

#### 1) Strategy 确认前

最适合 Debate 的位置之一。

因为此时：

- 方向开始成形
- 但还没固化成 PRD
- Debate 的结果很容易直接成为 PRD 输入

#### 2) PRD challenge 前

这个节点也很自然：

- 先写 PRD
- 再 decide 是走普通 challenge
- 还是对某个关键子议题开 Debate

#### 3) 高影响 decision 落盘前

例如：

- 要不要做某个方向
- 优先级怎么排
- 架构选型是否值得做

#### 4) 用户明确表达犹豫时

例如用户说：

- 我不太确定
- 这个方向对不对
- 我担心另一种方案可能更合理

这时主 Agent 可以轻提示一句：

> 这里可以开一场 Debate，看不同模型在不同优化目标下会怎么打。

### 原则

- 这是**提示**
- 不是自动判定
- 不是强制流程

---

### 5.2 结果应该如何异步插入主流程？

## 当前建议

**不要打断主流程，不要强行插入当前推理；而是在主流程自然检查点把它 surface 出来。**

### 推荐的异步回流链路

#### 第 1 层：后台启动

主 Agent 用：

```bash
pmagent debate start ...
```

在后台拉起。

这样：

- 当前会话可以继续推进
- Debate 在旁路跑完
- 不会强制线性等待

#### 第 2 层：底层事实源

Debate 结束后写：

- `status.json`
- `signal.json`

这是最底层状态来源。

#### 第 3 层：主流程感知

第一版最稳的建议是优先走：

- `current-state.json`
- `pmagent status`
- `pmagent review`
- `pmagent next`

也就是：

- Debate 跑完了
- current-state 里有 snapshot
- status / review / next 自然显示：
  - 有 debate 完成
  - 有 synthesis 待 review
  - 建议下一步先读 synthesis

#### 第 4 层：宿主增强（晚一期）

后续再加：

- hooks 的 SessionStart / UserPromptSubmit 注入提醒
- `workspace-summary` 的 `## Active Debates`

但这层建议作为第二阶段增强，不是 MVP 首先要做的东西。

---

## 建议拍板版

如果现在要把这 5 个点拍成一个“实现前共识”，我建议就按下面这版定：

### 1. 调用方式
- **选**：独立 CLI + CLI 执行器
- **不选**：第一版就直接下沉成原生 provider API / 宿主内 subagent orchestrator

### 2. Prompt
- **选**：优化目标对立 + 主 Agent 提议候选轴 + 人确认 + Round 0/1/2
- **不选**：简单正反方 / 自由讨论

### 3. 落盘
- **选**：`context/debates/<topic>/round-N-{pro,con}.md`
- **不选**：直接写进 `decisions/` / `prd/`

### 4. 输出
- **选**：结构化 `synthesis.md`
- **不选**：主 Agent 临时读 round 再自己总结

### 5. 提供时机与异步回流
- **选**：关键节点 soft reminder + 用户主动触发 + `current-state/status/review/next` 回流
- **不选**：自动触发 / monitor 进程 / 直接打断主流程

---

## 还可以暂时不拍死的点

这些可以留到下一轮设计或实现时再定：

1. 何时把 CLI 执行器下沉成原生 provider API
2. 是否保留 inject / pause / resume
3. synthesis 是否需要独立 synthesizer executor / provider slot
4. `workspace-summary` 是否第一版就展示 `## Active Debates`

---

## 一句话结论

**Debate 当前第一版不应该先做成“原生 provider SDK 编排”，而应该先做成“主 Agent 在关键节点发起的一条独立 CLI 异步旁路”，由 orchestrator 程序化调用 `codex` / `claude` 这类 CLI 执行器完成每轮辩论，每轮落盘到 `context/debates/`，最后产出 `synthesis.md`，再通过 `current-state / status / review / next` 回流主流程。**
