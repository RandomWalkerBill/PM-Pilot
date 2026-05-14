# pmagent Debate 最终汇总文档

## 文档定位

这份文档用于把目前关于 Debate 的讨论结果收束成一个**可直接指导后续实现**的最终汇总版本。

它不再展开历史分歧，也不重复所有中间推导，而是只回答：

1. Debate 到底是什么
2. 第一版应该怎么做
3. 哪些决策已经拍板
4. 哪些点明确留到第二阶段

这份文档默认高于：

- `docs/pmagent-debate-alignment-summary.md`
- `docs/pmagent-debate-implementation-plan.md`

在“当前最终共识”这一层面上的零散表述。  
如果将来要翻案，请优先改这份文档。

---

## 一句话结论

> **Debate 第一版做成一个由主 Agent 发起的独立 CLI 异步旁路：`pmagent` 负责 orchestrator、轮次协议、落盘协议和主流程回流；真正的模型执行面先用 `codex exec` / `claude -p` 这类 CLI 执行器；每个辩手维护自己的 session，按 3 轮结构化对打，最终产出 `synthesis.md`，再通过 `current-state / status / review / next` 异步回流主流程。**

---

## 1. Debate 的最终定位

## 1.1 它是什么

- **一个 step，不是 mode，不是 phase**
- 一个用于“观点深化 / 揭示张力 / 暴露盲区”的旁路机制
- 主 Agent 发起，但不亲自下场辩论
- 运行在独立 CLI 进程中
- 产物首先落在 `context/debates/`，属于 context artifact，不是 canonical decision

## 1.2 它不是什么

- 不是 `conviction-forge` 的替代品
- 不是自动触发系统
- 不是自动修改 PRD / Requirement / decisions 的 mutation engine
- 不是为了追求“两个模型握手言和”
- 不是宿主里两个 agent 随便聊一聊就算 Debate

## 1.3 它的核心价值

Debate 的主要价值不是“给出一个统一答案”，而是输出三类高价值信号：

1. **收敛点**
   - 双方都认同的结论
   - 价值：确认性，中等

2. **分歧点**
   - 双方无法说服对方的核心张力
   - 价值：判断性，最高

3. **意外发现**
   - 原始命题未覆盖但在辩论中浮现的新视角
   - 价值：激发性，高

人仍然是裁判，不是辩手。

---

## 2. 调用方式：最终选择

## 2.1 已拍板结论

**用 CLI 当执行器。**

也就是说：

- 主 Agent：
  - 决定何时发起 Debate
  - 用 Bash 后台拉起 `pmagent debate start ...`
  - 之后读取 `synthesis.md`

- `pmagent debate` orchestrator：
  - 负责 round 编排
  - 负责 prompt 拼装
  - 负责 session 管理
  - 负责文件落盘
  - 负责 synthesis 生成

- 底层模型执行器：
  - `codex exec`
  - `claude -p`

## 2.2 为什么不先直接接 API

因为当前优先级是：

1. 先把 Debate 机制跑通
2. 先验证：
   - 双模型对打是否真的有价值
   - 3 轮结构是否有效
   - synthesis 是否能被主流程消费
3. 不要第一版就被 provider SDK 抽象拖慢

所以当前更务实的取向是：

- **pmagent 控协议**
- **CLI 控执行**

## 2.3 subagent 的地位

### 不是“绝对不行”

如果宿主支持：

- 每个 subagent 绑定不同模型
- 或绑定不同 API

那么 subagent 是可以做 Debate 的。

### 但第一版不选它作为 canonical 形态

原因不是“它没能力”，而是当前更优先：

- 固化独立进程边界
- 固化 round 文件协议
- 固化状态文件协议
- 固化主流程回流方式

所以第一版排除的是：

- **宿主内 orchestrator**

不是排除：

- **宿主 CLI 本身**

---

## 3. Debate 的最终执行拓扑

```text
主 Agent（Claude Code / Codex）
  └─ Bash(run_in_background=true)
      └─ pmagent debate start --workspace <ws> --thesis "..."
          └─ Debate Orchestrator（Python）
              ├─ Defender executor:  claude -p / codex exec
              ├─ Attacker executor:  codex exec / claude -p
              ├─ 维护两条会话
              ├─ 每轮读取 / 写入 round 文件
              └─ 最终生成 synthesis.md

主流程后续通过：
  current-state.json
  pmagent status
  pmagent review
  pmagent next
感知 Debate 完成状态
```

---

## 4. 每个辩手如何维护会话

这部分是最新补充后已经明确的重要实现点。

## 4.1 核心原则

**每个辩手各自维护一个独立 session。**

这样做的原因：

- 更像真实连续辩论
- 不必每轮都完全丢失上下文
- 比手工操纵交互式 TUI 更适合程序化编排

---

## 4.2 Claude 的 session 管理

Claude CLI 已明确支持：

- `--session-id`
- `--resume`
- `--continue`

### 最佳实践

**启动时自己指定 sessionId。**

例如：

```powershell
$defenderSession = [guid]::NewGuid().ToString()
claude -p --session-id $defenderSession "Round 0 prompt ..."
```

这样后续无需再“查找”：

```powershell
claude -p --resume $defenderSession "Round 1 prompt ..."
```

### 结论

Claude 侧的 sessionId 最好由 orchestrator **自己生成并持久化**。

---

## 4.3 Codex 的 session 管理

Codex CLI 当前明确支持：

- `codex exec`
- `codex exec resume <SESSION_ID> <PROMPT>`

但没有像 Claude 一样直接暴露“启动时指定 sessionId”的简单参数。

### 最佳实践

**第一轮执行后，从本地 session 文件中读取 sessionId。**

Codex 的 session 文件位于：

```text
~/.codex/sessions/YYYY/MM/DD/rollout-....jsonl
```

文件第一行通常包含：

```json
{"type":"session_meta","payload":{"id":"<SESSION_ID>", ...}}
```

也可以从：

```text
~/.codex/session_index.jsonl
```

中读取。

### 后续续聊

```powershell
codex exec resume <SESSION_ID> "Round 1 prompt ..."
```

### 结论

Codex 侧的 sessionId 最好采用：

1. Round 0 执行
2. 读取本地 `session_meta.payload.id`
3. 持久化到 `run.json`
4. 后续全部 `resume`

---

## 4.4 run.json 中必须持久化 session 信息

建议 `run.json` 至少包含：

```json
{
  "topic": "mvp-vs-complete-experience",
  "workspace": "<ws>",
  "thesis": "...",
  "round_count": 3,
  "executors": {
    "defender": {
      "kind": "claude",
      "session_id": "..."
    },
    "attacker": {
      "kind": "codex",
      "session_id": "..."
    }
  }
}
```

这样后续 round 不需要再次猜测或扫描会话。

---

## 5. Prompt 设计：最终选择

## 5.1 总原则

**不是简单正反方，而是“优化目标对立”。**

坏方案：

- A 支持 X
- B 反对 X

好方案：

- Defender：优先维护当前方向在某个目标下的合理性
- Attacker：优先揭示当前方向在另一目标下的代价和盲区

## 5.2 对立轴来源

对立轴不应该：

- 全靠人手写
- 也不应该完全自动生成后直接开跑

最终选择是：

> **默认交互流里，由主 Agent 先提 2–3 组候选轴，用户确认或微调。**

流程：

1. 用户表达要开一场 Debate
2. 主 Agent 基于当前上下文提 2–3 组候选对立轴
3. 用户选择 / 微调 / 重写
4. 主 Agent 再调用 `pmagent debate start --axis "..."`

## 5.3 推荐的 3 轮结构

### Round 0：独立起手

- 双方只看 thesis / axis / context
- **互相看不到对方内容**

目的：

- 暴露原生视角
- 避免一开始被对方叙事框住
- 提高意外发现概率

### Round 1：交锋

- 双方看对方 Round 0
- 各自攻击对方最弱的一环

### Round 2：深入

- 双方看 Round 1
- 聚焦最无法调和的那个分歧点

## 5.4 硬性规则

Prompt 中应显式加入：

- 禁止“取决于情况”
- 禁止“两边都有道理”
- 禁止“可以结合一下”
- 每轮最多 3 个核心论点
- 必须回应对方上一轮最强的一条主张
- 每轮必须以一句单主张结论结束

---

## 6. 每轮 round 产物落在哪里

## 6.1 最终结论

**每轮单独落盘，统一放到当前 workspace 的 `context/debates/<topic>/` 下。**

不直接写进：

- `decisions/`
- `strategy/`
- `prd/`

因为 round 本质上还是：

- context artifact
- 辩论素材
- synthesis 输入

而不是 canonical decision。

## 6.2 推荐目录结构

```text
workspaces/<workspace>/
  context/
    debates/
      <YYYY-MM-DD>-<topic-slug>/
        run.json
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

## 6.3 各文件职责

- `run.json`
  - thesis / topic / executors / session ids / round count

- `axis.json`
  - 候选轴与最终选择轴

- `status.json`
  - `queued / running / completed / failed`
  - 当前轮次

- `signal.json`
  - 面向主流程的轻量通知

- `round-N-{pro,con}.md`
  - 每轮原始输出

- `synthesis.md`
  - 唯一正式结论入口

---

## 7. 最终输出：synthesis.md

## 7.1 最终结论

**Debate 的正式输出只有一个：`synthesis.md`。**

主 Agent 不应该在第一版中：

- 重新读完整 round 再自己临时总结
- 自动改 PRD
- 自动写 decisions
- 自动回写 Requirement

关于生成责任，当前最终共识是：

> **`synthesis.md` 不是纯规则生成，也不是主流程 Agent 自由发挥生成，而是由 Debate orchestrator 在收集所有 round 文件后，先做规则化预处理，再调用一个专门的 synthesizer CLI 执行器按固定结构生成，最后再经过规则校验后落盘。第一版默认由一个独立的 CLI 执行器承担 synthesizer 角色。**

也就是说，`synthesis.md` 的生成链路是：

```text
round 文件
  ↓
规则预处理
  ↓
synthesizer CLI
  ↓
规则校验
  ↓
synthesis.md
```

## 7.2 synthesis 的生成机制与责任划分

### A. 规则预处理负责什么

在调用 synthesizer 之前，orchestrator 先做机械整理，不做自由总结。

这一层负责：

- 读取：
  - `thesis`
  - `chosen axis`
  - `round-0/1/2` 的所有文件
  - `run.json`
  - `status.json`
- 提取每轮的基础结构信息，例如：
  - 每轮最后一句单主张结论
  - 是否出现明显 hedging
  - 是否出现 acknowledgement / adjust
  - 是否存在明显 repetition
- 形成一份中间摘要，作为 synthesizer 的辅助输入

这一层的职责是：

- 收集输入
- 整理结构
- 打质量标记

**不负责判断收敛点、分歧点、意外发现。**

### B. synthesizer CLI 负责什么

synthesizer 是一个独立执行槽位，不与 Defender / Attacker 某一轮输出混用。

它的职责是：

- 归纳收敛点
- 提炼核心分歧点
- 识别意外发现
- 提取修正记录
- 生成 `Recommended Next Action`

它不是回答“谁赢了”，而是回答：

- 哪些点双方都承认
- 哪些点双方还没打穿
- 哪些点值得人来裁决
- 主流程下一步该如何消费这场 Debate

### C. 规则校验负责什么

synthesizer 输出后，不直接落盘，还要经过规则校验。

校验至少包括：

- 是否包含必需 section
- `Core Divergences` 中是否包含：
  - Defender 立场
  - Attacker 立场
  - 人需要裁决的判断
- `Quality Flags` 是否保留了预处理阶段已经发现的信号

如果不通过：

- 不写正式 `synthesis.md`
- 将状态记为 `synthesis_incomplete` 或 `synthesis_failed`
- 允许 orchestrator 重试或人工介入

## 7.3 synthesis 结构

推荐固定成：

```markdown
# Debate Synthesis: <topic>

## Thesis

## Chosen Axis

## Convergence

## Core Divergences
- Defender 立场
- Attacker 立场
- 人需要裁决的判断

## Unexpected Findings

## Acknowledgements / Adjustments

## Quality Flags

## Recommended Next Action
```

## 7.4 synthesis 的输入边界

synthesizer 的输入来源固定为：

- `thesis`
- `chosen axis`
- 所有 round 文件
- 规则预处理结果
- 质量标记

默认**不直接读取主流程 Agent 的临时思考上下文**。

这样做的目的是保证：

- synthesis 的依据可追溯
- synthesis 与主流程自由发挥解耦
- 将来更容易重跑 / 对比 / 调试

## 7.5 synthesis 的职责

不是回答：

- 谁赢了

而是回答：

- 哪些点双方都承认
- 哪些点还没打穿
- 哪些点值得人裁决
- 下一步该如何被主流程消费

---

## 8. Debate 何时提供给用户

## 最终结论

**不做自动触发，只做关键节点 soft reminder + 用户主动触发。**

### 推荐时机

1. **需求澄清和调研之间**
   - 也就是当前方向已经初步成形、准备从 clarifying 进入 researching，但还存在关键张力时。

2. **PRD 生成之后**
   - 不要求等到 challenge 正式开始，只要 PRD 已生成，就可以针对某个关键子议题开一场 debate。

3. **高影响 decision 落盘前**
   - 尤其是会直接影响 strategy、范围取舍、PRD 主方向或资源分配的 decision。

4. **用户明确表达犹豫时**
   - 例如“我不太确定”“这个方向对不对”“要不要再看看别的角度”。

### 补充原则

- 这四个节点是 **推荐提供 Debate 的主入口**。
- 它们代表的是“主流程里最值得显式暴露张力”的时刻，而不是“系统必须自动发起 Debate”的时刻。
- 在实现上，优先通过：
  - skill 合同中的 soft reminder
  - `SessionStart` / `UserPromptSubmit` 的 hooks 注入
  来把 Debate 显式带到主流程里。

### 原则

- 这是提示，不是强制
- 这是提醒有工具可用，不是系统自动判断“必须开辩”

---

## 9. Debate 结果如何异步插入主流程

## 9.1 最终结论

**不要打断主流程，而是在自然检查点把结果 surface 出来。**

## 9.2 推荐回流链路

### 第一层：后台运行

主 Agent：

```bash
pmagent debate start ...
```

后台拉起 Debate。

### 第二层：底层事实源

Debate 写：

- `status.json`
- `signal.json`

### 第三层：主流程感知

第一版优先通过：

- `current-state.json`
- `pmagent status`
- `pmagent review`
- `pmagent next`
- `pmagent debate review --topic <slug>`
- `pmagent debate resolve --topic <slug> --accepted|--rejected|--deferred`

来显示：

- 有 debate 完成
- 有 synthesis 待 review
- 建议下一步先读 synthesis

其中：

- `pmagent debate review --topic <slug>`
  - 负责写入 `current-state.json.debate_review`
  - 不占用 `active_step` / `pending_user_decision` 的单槽位
- `pmagent debate resolve ...`
  - 负责结束 review
  - 清理 `debate_review` 中对应 topic
  - 写入 `review.json`

### 第四层：宿主增强（晚一期）

后续再加：

- hooks 注入提醒
- `workspace-summary` 的 `## Active Debates`

但这不是第一版最先要做的事情。

---

## 10. 与主流程的关系

## 10.1 PRD 之前

如果 Debate 发生在 PRD 之前：

- 它就是 PRD 的输入
- 不存在复杂级联问题

## 10.2 PRD 之后

如果 Debate 发生在 PRD 之后：

- Debate 只产出 synthesis
- 人裁决是否需要改 PRD
- 如需修改，沿用 maintenance 思路处理

也就是说：

- Debate = 新信号源
- maintenance = 现有治理面

---

## 11. 当前已经拍板的内容

### 已拍板

1. Debate 是 step，不是 mode
2. Debate 跑在独立 CLI 进程里
3. 第一版执行器优先用 `codex exec` / `claude -p`
4. 每个辩手维护自己的 session
5. Prompt 采用优化目标对立
6. 默认由主 Agent 提议 axis，再由用户确认
7. 使用 3 轮结构：Round 0 / 1 / 2
8. 每轮落到 `context/debates/<topic>/`
9. synthesis 采用“规则预处理 → 独立 synthesizer CLI → 规则校验”链路
10. `pmagent debate review / resolve` 负责 review 状态 owner
11. MVP 不做 blocking debate gate，只做可见性与文档边界保护
12. 不自动触发，只做关键节点提示
13. 异步通过 `current-state / status / review / next` 回流
14. PRD 后回流走 maintenance 思路

### 暂不拍死

1. 是否保留 inject / pause / resume
2. `workspace-summary` 是否第一版就展示 `## Active Debates`
3. 何时把 CLI 执行器进一步下沉成原生 provider API
4. blocking debate 是否值得在第二期引入

---

## 12. 当前推荐的实现顺序

### 第一阶段

先做：

1. `pmagent debate start`
2. CLI 执行器适配：
   - `codex exec`
   - `claude -p`
3. session 管理：
   - Claude 启动时指定 sessionId
   - Codex 首轮后读取 sessionId
4. 3 轮 orchestrator
5. round 文件落盘
6. `synthesis.md` 生成

### 第二阶段

再做：

1. `current-state.json` 的 debate snapshot
2. `pmagent status / review / next` 的 Debate 展示
3. hooks 注入
4. `workspace-summary` 展示

### 第三阶段

再决定是否要：

1. 接入原生 provider API
2. 支持 inject / pause / extend
3. 做成本统计和更强的执行器抽象

---

## 最终一句话

**Debate 当前的最终方案，不是“宿主里随便拉两个 agent 聊一下”，也不是“第一版先把 provider SDK 抽象做满”，而是“主 Agent 发起一个独立 CLI Debate 任务，由 `pmagent` orchestrator 程序化调用 `codex` / `claude` 两类 CLI 执行器，维护各自 session，按 3 轮结构化对打，落盘到 `context/debates/`，最后产出 `synthesis.md` 并异步回流主流程”。**
