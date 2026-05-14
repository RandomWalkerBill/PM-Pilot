# pmagent Debate 模式设计

## 文档定位

这是一份 **实现设计文档**，把此前对话中形成的 12+ 条设计共识规范化，并把它和当前 pmagent 代码/文件协议/hooks 体系对接。

文档范围：
- Debate 功能的定位、边界、不做什么
- 执行模型（独立 CLI 进程 + 文件汇合）
- 执行器层、Prompt 工程、Synthesis 规范
- 落盘结构和 CLI 命令
- 与主流程（phase / workspace-summary / hooks / maintenance）的接入方式
- MVP 切片与分期

文档**不**范围：
- 具体 prompt 全文（会在 `templates/` 单独落一份）
- 辩论质量量化评估（需要真实数据后再谈）
- 多语言 / 多 workspace 并发执行等增强形态

真相源优先级参考 `config/agent-workflow.yaml`；本文件在"Debate 实现边界"这一专题上是当前最新共识。

---

## 0. 决策锁定（2026-04-21 对齐）

以下 5 条决定在对齐讨论中锁定，覆盖先前文档里同主题的陈述。如果未来要翻盘必须显式改这一节。

| # | 决策 | 反对选项（未选） | 核心理由 |
| --- | --- | --- | --- |
| 1 | **调用方式：独立 CLI 进程**，主 Agent 用 `Bash(run_in_background=true)` 拉起；**第一版执行器优先用 `codex exec` / `claude -p` 这类 CLI** | 宿主内 subagent / 第一版直接做原生 provider SDK | 当前目标是先把 Debate 机制跑通，而不是先做满 provider 抽象。CLI 仍然能程序化调用不同模型执行面，同时保留独立进程、落盘协议和异步回流 |
| 2 | **Prompt：优化目标对立 + 硬约束反和稀泥 + 3 轮递进 0/1/2** | 简单正反方 / 纯自由讨论 | MAD 等调研验证；对话里也早期否决过简单正反方 |
| 3 | **落盘：每轮分别落在 `workspaces/<ws>/context/debates/<topic>/round-N-{pro,con}.md`** | 写进 `decisions/` 或 `prd/` | debate 是 context 素材，不是 decision；`pre_write_guard` hook 做兜底 |
| 4 | **输出：Markdown-first**；每轮直接落 `round-N-{pro,con}.md`，最终产出 `synthesis.md` 三段式（收敛/分歧/意外）+ 修正记录 + 质量标记，默认由独立 synthesizer CLI 生成 | 强依赖 JSON schema 输出 / 主 Agent 亲自写 synthesis / Defender 兼任总结 | CLI 执行器对 JSON schema 的支持不完全对称；Markdown 契约 + 规则校验更适合当前独立进程形态 |
| 5 | **时机：关键节点 skill 合同 soft reminder + 用户主动触发**；异步插入走 `signal.json` + `## Active Debates` + hooks 注入 | 自动触发 / monitor 进程 | 高阶判断应属人；关键节点是工作流天然断点 |

### 仍待拍板的 3 件事

以下三项尚未最终拍板，文档按当前版本继续推进，真实落地前需要确认：

1. **是否保留 Round 0（独立起手）** —— 带来 +2 次执行器调用但承担意外发现的主要信号源。默认 "要"
2. **是否同时落 agent event bus** —— `<data_dir>/ops/agent-events/<date>.jsonl`。做了 debate/observation/maintenance 的统一看板能力一次解锁。默认 "晚一期再说，MVP 先用 signal.json"
3. **synthesis 生成模型的默认项** —— 当前默认使用显式独立的 `synthesizer` executor slot；后续再观察是否需要让 primary 兼任作为 fallback

---

## 1. 背景与定位

### 1.1 为什么做

当前 pmagent 的观点深化能力依赖两条路径：

- `conviction-forge`：AI 扮演反方挑战用户，是 **人 ↔ AI 对练**，AI 激发人的判断
- `challenge-prd`：AI 多视角审查 PRD，是**单向审查**，不是双向辩论

这两条路径都绕不开一个瓶颈：**当前会话里的 AI 已经参与了推导，它的思维路径和人的路径高度相关，很难再"跳出"去看。**

Debate 的价值是**显式引入另一个独立 AI 实例**，让"没看过这条路径"的模型去挑战"参与过这条路径"的共识。它的产出重点**不是共识**（共识经常是 RLHF 驱动的和稀泥），而是：

1. 收敛点 —— 双方都无法驳倒的结论（确认性价值，中等）
2. 分歧点 —— 双方无法调和的核心张力（判断价值，**最高**）
3. 意外发现 —— 辩论过程中浮现的、原始命题未覆盖的新视角（激发价值，高）

人是裁判，不是辩手。

### 1.2 它是什么

| 属性 | 取值 |
| --- | --- |
| 工作流层级 | **step**，不是 mode；`skills/steps/debate/skill.md`，与 `challenge-prd` 平级 |
| 执行位置 | **独立 CLI 进程**（`pmagent debate start` 在另一个终端 / `run_in_background`） |
| 参与方 | 两个 AI，都是由 orchestrator 调用的 CLI 执行器（后续可下沉到 provider API）；不复用主 Agent 会话 |
| 多轮结构 | 3 次交互：Round 0（独立起手）→ Round 1（交锋）→ Round 2（深入） |
| 主 Agent 角色 | **读** synthesis.md 来消费结果；不参与执行；不写 round 内容 |
| 是否改 phase | 否，debate 是**平行通道**，不动 clarifying/researching/delivery/maintaining |
| 对 workspace 状态的影响 | 只新增 `context/debates/<topic>/` 子树与 `## Active Debates` summary 段落 |

### 1.3 它不是什么

- **不是 Forge 的升级**：Forge 保留原样，面向人的判断打磨
- **不是自动触发系统**：不单开 monitor 进程、不让主 Agent 主动"建议开 debate"做高阶语义判断
- **不追求共识**：两个 AI 握手言和对人没有决策价值
- **不做 pause/resume**：默认轮数少（3 次交互），跑完看结果就行
- **不做跨议题上下文累积**：每议题独立，靠底层 CLI 所绑定模型服务的 prompt caching 消化重复 context 成本

---

## 2. 执行模型

### 2.1 整体拓扑

```
┌──── 主 Agent 会话（Claude Code / Codex） ───────────────────┐
│  用户："帮我对 X 开一场 debate"                              │
│  主 Agent: Bash(command="pmagent debate start ...",          │
│                 run_in_background=true) → 立即返回 task_id   │
│  主 Agent 继续推进主流程 clarifying / researching / ...      │
│            ↑                                                  │
│            │ 文件汇合（signal.json / summary / hooks）        │
└────────────┼──────────────────────────────────────────────────┘
             │
┌────────────┴──── Debate 独立进程（pmagent debate start） ─────┐
│  Orchestrator (Python) 循环 3 轮，每轮对每一方各调一次 API    │
│    │                                                           │
│    ├── Executor A (primary, e.g. `claude -p`) ← Defender      │
│    └── Executor B (secondary, e.g. `codex exec`) ← Attacker   │
│                                                                │
│  每轮产出实时落盘 → round-N-{pro,con}.md + status.json        │
│  完成时生成 synthesis.md + signal.json                        │
└────────────────────────────────────────────────────────────────┘
```

关键设计：

- **CLI 进程 ≠ 一次模型调用**。orchestrator 是一个长期运行的 Python 进程，它循环调用 CLI 执行器 N 次来实现多轮辩论（见 §2.2.1）
- **主 Agent 感知到的"异步"来自 `run_in_background=true`**，不是来自 subagent。拉起的 Bash 命令立即返回 task_id，后台继续跑
- **不 poll**：主 Agent 通过 `signal.json` + `workspace-summary "## Active Debates"` + hooks 注入得知状态
- **复刻 observation 的解耦模式**：observation 独立跑 + `observe audit` 汇合。debate 不新增后台任务/调度系统

### 2.2 轮次结构（基于 MAD / Agent4Debate 等调研验证）

| 轮次 | 双方是否互相可见 | 任务 | 产出 |
| --- | --- | --- | --- |
| Round 0 | **否**（各自只看 context） | 独立陈述立场 | `round-0-pro.md`, `round-0-con.md` |
| Round 1 | 是（看到对方 Round 0） | 针对性反驳，指出对方最弱论据 | `round-1-pro.md`, `round-1-con.md` |
| Round 2 | 是（看到 Round 1） | 聚焦：压到"最本质的一个分歧" | `round-2-pro.md`, `round-2-con.md` |

为什么要 Round 0：如果进攻方一上来就看到防守方陈述，会被防守方的叙事"框住"，意外视角容易丢失。独立起手是**意外发现信号**的主要来源。默认 3 次交互；人可 `pmagent debate extend --rounds N` 追加。

### 2.2.1 orchestrator 的 3 轮实现模式

无论底层是 **CLI 执行器** 还是未来的 **provider API**，多轮对话的本质都一样：**orchestrator 在外部累积历史，并在每轮把当前完整上下文重新交给执行面**。执行面本身不替你管理 debate 状态机。

subagent 形态在这个问题上也没有本质差别 —— 它们都是"外部 orchestrator 循环调用某种模型执行面"，区别只在谁是 orchestrator、以及执行面暴露成 CLI / 宿主任务 / SDK 的哪一种形式。

但要特别注意：

> **CLI 执行器形态下，并不存在原生 `messages[]` / `system` 这种结构化接口。**  
> `claude -p` / `codex exec` 接受的是一整个 prompt 字符串，返回的是一个响应字符串。  
> 第一版因此采用 **Markdown-first 契约**：orchestrator 把 system prompt、完整历史轮次和本轮任务扁平化成文本 blob，要求执行器直接输出固定 heading 的 markdown；JSON 仅作为兼容 fallback，而不是主协议。

也就是说，当前第一版的真实调用更接近：

```python
# orchestrator 伪代码（CLI 执行器形态）

system_prefix = build_defender_system(project_context, optimization_objective, constraints)
history_blocks = []

def render_prompt(system_prefix: str, history_blocks: list[str], task_block: str) -> str:
    return (
        system_prefix
        + "\n\n## 历史记录\n"
        + ("\n\n".join(history_blocks) if history_blocks else "(none)")
        + "\n\n## 本轮任务\n"
        + task_block
    )

# ---- Round 0：独立起手 ----
prompt_0 = render_prompt(system_prefix, history_blocks, "Round 0：独立陈述立场。")
resp_0 = executor_a.run(prompt_0)
write("round-0-pro.md", resp_0)
history_blocks.append("### Round 0 / 我方\n" + resp_0)

# ---- Round 1：交锋 ----
round_0_con = read("round-0-con.md")
history_blocks.append("### Round 0 / 对方\n" + round_0_con)
prompt_1 = render_prompt(
    system_prefix,
    history_blocks,
    "Round 1：指出对方最弱的假设并反驳。",
)
resp_1 = executor_a.run(prompt_1)
write("round-1-pro.md", resp_1)
history_blocks.append("### Round 1 / 我方\n" + resp_1)

# ---- Round 2：聚焦最本质分歧 ----
round_1_con = read("round-1-con.md")
history_blocks.append("### Round 1 / 对方\n" + round_1_con)
prompt_2 = render_prompt(
    system_prefix,
    history_blocks,
    "Round 2：围绕最无法调和的那一个分歧点给出最终聚焦立场。",
)
resp_2 = executor_a.run(prompt_2)
write("round-2-pro.md", resp_2)

# ---- Synthesis ----
synthesis_prompt = build_synthesis_prompt(thesis, axis, all_round_files_concat, preprocessed_flags)
synthesis = synthesizer_exec.run(synthesis_prompt)
write("synthesis.md", synthesis)
write_signal_completed()
```

这也意味着当前 CLI 形态下有两个现实限制：

1. `user` / `assistant` 的角色边界退化成文本标记（例如 `### 我方` / `### 对方`）
2. 无法像直连 SDK 那样精细控制 prompt caching 的 cache breakpoint

未来如果下沉到 SDK 形态，才是下面这种更理想的结构化接口：

```python
resp = provider.call(system=system_prompt, messages=history)
```

所以：

- **第一版 CLI 形态 = 文本 blob 编排**
- **第二版 SDK 形态 = 结构化 messages 编排**

**总账（每议题）：**

| 调用 | Defender (primary) | Attacker (secondary) | Synthesizer |
| --- | --- | --- | --- |
| Round 0 | 1 次 | 1 次 | — |
| Round 1 | 1 次 | 1 次 | — |
| Round 2 | 1 次 | 1 次 | — |
| Synthesis | — | — | 1 次 |
| **合计** | **3** | **3** | **1** |

CLI 形态下是否命中 cache 取决于宿主和底层模型服务的自动行为；不要假设 R0 之后全部命中。实际命中率以账单和日志观测为准。参考 §3.4。

### 2.3 signal.json 协议

Debate 完成或到达里程碑时写：

```json
{
  "event": "completed",
  "topic": "event-driven-vs-polling",
  "rounds_completed": 3,
  "started_at": "2026-04-21T10:30:00+08:00",
  "completed_at": "2026-04-21T10:33:12+08:00",
  "summary_oneline": "3 轮辩论完成，在工程可行性和用户价值上存在核心分歧",
  "action_needed": "review_synthesis",
  "synthesis_path": "workspaces/<ws>/context/debates/event-driven-vs-polling/synthesis.md"
}
```

`event` 取值：`started | round_completed | completed | failed | human_injected | stopped`

### 2.4 与主流程的汇合点

| 汇合点 | 机制 | 类比 |
| --- | --- | --- |
| `pmagent status` / `pmagent route` | 输出里列出 active debates 数量与完成状态 | `observation backlog` |
| `workspace-summary.md` | 新增 `## Active Debates` 段落，summary 一行摘要 + 指向 synthesis | `## Recent Observation` |
| Claude Code hooks | `state_surface` 在 UserPromptSubmit 时也扫 `context/debates/*/signal.json`，有未读 synthesis 就注入提示 | 现有 backlog_visibility |
| 手动 | `pmagent debate show` / `pmagent debate synthesis --workspace <ws>` | — |

### 2.5 为什么当前先不用 subagent 形态

对齐讨论里曾考虑把 debate 直接做成 Claude Code / Codex 的 subagent。现在更准确的结论是：

- **subagent 不是绝对不能做**
- 但 **当前第一版不选它作为 canonical 形态**

原因不是“subagent 一定只能同模型”，而是当前这版更想优先得到：

- 明确的独立进程边界
- 明确的 round 文件落盘
- 明确的状态文件与回流协议
- 尽量少依赖宿主内部的 agent schema

| 维度 | CLI 进程 + CLI 执行器（当前决定） | 宿主 subagent（未选） |
| --- | --- | --- |
| 多轮能力 | orchestrator 循环调用执行器 N 次，见 §2.2.1 | 同样能做，但 orchestrator 放进宿主 |
| 跨模型能力 | ✓ 只要底层 CLI 能绑不同模型，就可真实异质 | 取决于宿主是否支持 per-agent 不同模型 / API |
| 非阻塞 | ✓ `run_in_background=true` 给主 Agent | ✓ 也能做，但依赖宿主任务机制 |
| 与主 Agent 的解耦 | 进程级完全独立，signal 文件汇合 | 逻辑更贴宿主 turn / task 生命周期 |
| 产物可追溯 | 每轮落成 `.md` 文件，任意工具可读 | 也能落文件，但更容易把细节散进宿主 transcript |
| 对当前阶段的实现成本 | 更低：直接调用 `codex` / `claude` 即可 | 中：要额外适配宿主 subagent 编排方式 |
| 对长期可迁移性 | 更好 | 更依赖宿主内部能力 |

**当前不选 subagent 的核心理由**：不是能力不够，而是当前优先级是“先把 Debate 协议和文件回流跑通”，这件事用独立 CLI 进程 + CLI 执行器更直接。

---

## 3. 执行器层（CLI-first）

### 3.1 作用域

**全局 config，不是 workspace 级。** 落在 `<data_dir>/config/debate-executors.yaml`。所有 workspace 共享一份候选集。

理由（对话确认）：
- Debate 的质量来自"有两个够强的模型"，不来自 workspace 专属调校
- workspace 级覆盖会引入维护成本，且用户真要特定模型时可以直接改全局

### 3.2 配置形态

```yaml
# <data_dir>/config/debate-executors.yaml
schema_version: 1
defaults:
  primary: claude
  secondary: codex
# "primary" 担任 Defender，"secondary" 担任 Attacker。见 §4。

executors:
  - id: claude
    kind: cli
    command: claude
    args_template:
      - -p
      - --output-format
      - text
    enabled_in: [claude-code, codex, vscode]
  - id: codex
    kind: cli
    command: codex
    args_template:
      - exec
    enabled_in: [claude-code, codex, vscode]

# 环境 fallback：当 defaults.secondary 在当前环境不可用时按序尝试
environment_fallback:
  codex:
    secondary: [claude]
```

### 3.3 环境适配

运行环境由 `pmagent debate start` 启动时推断：

| 检测项 | 用来判断什么 |
| --- | --- |
| 环境变量 `PMAGENT_HOST_AGENT`（用户可手工设置） | claude-code / codex / vscode / unknown |
| `.claude/` 存在 + 无 `.codex/` | claude-code |
| `.codex/` 存在 | codex |
| 都无 | 用 `defaults.primary / secondary`，不做 fallback |

**第一版只有 1 类 backend 实现**：`cli`。不先做插件体系。未来如要下沉到直连 API，再补 `anthropic` / `openai-compatible` 等 backend。

### 3.4 成本边界

- 默认 3 次交互 = 每方 3 次 CLI 调用 = **6 次执行器调用/议题**
- 每议题独立对话，**project context 在逻辑上固定注入**
- CLI 形态下的 prompt caching 依赖宿主 / 底层模型服务的自动行为，**实际命中率以账单和日志观测为准**
- 当前第一版**不能**像直连 SDK 那样显式指定 cache breakpoint 或 cache_control
- 不做跨议题的上下文压缩或复用 —— 命中缓存就赚，没命中就多花一次全量 context 成本
- Synthesis 生成 = 1 次额外执行器调用（primary），按其底层模型服务计费

---

## 4. 对立轴与角色分配

### 4.1 对立轴来源（主 Agent 提议 + 人裁决）

```
用户：我要对 X 开一场 debate
         │
         ▼
主 Agent 基于当前上下文提 2-3 组候选对立轴
         │
         ▼
用户裁决：
  - 选 A / 选 B / 选 C
  - 选 A 并微调措辞
  - 全部拒绝，我手写对立轴
         │
         ▼  `pmagent debate start --axis "..."`
确认后进入 Round 0
```

| 辩题类型 | 默认对立轴（候选生成时优先考虑） |
| --- | --- |
| 方案选型 | 用户体验 vs 工程简洁性 |
| 范围取舍 | 验证速度 vs 体验完整性 |
| 优先级排序 | 短期收益 vs 长期复利 |
| 架构决策 | 灵活性/可扩展 vs 当前简单性 |
| 商业方向 | 用户增长 vs 单用户价值深度 |
| 竞争策略 | 差异化 vs 跟随市场验证 |

### 4.2 角色分配（Defender / Attacker）

对话确认的规则：

- **primary（主模型）= Defender**：当前会话主模型已参与了共识推导，它自然擅长**维护并深化**当前方向，论证更有力、更具体
- **secondary（外部模型）= Attacker**：没参与过 context 构建的"局外人视角"，更可能提出意外角度
- 不做 trait 匹配、不做随机分配，简单且有效
- 用户可用 `--pro-exec / --con-exec` override

**注意**：这里 primary 的"是主模型"特指执行器身份（例如 `claude` / `codex`），**不是**"主 Agent 会话本身"。因为执行在独立 CLI 进程里，两方都是由 orchestrator 程序化调用。

---

## 5. Prompt 工程

### 5.1 核心原则

- **基于优化目标对立，不做简单正反方**
- **硬性禁止和稀泥**
- **每轮限论点数**（默认 3 个），每个论点必须含具体证据/场景
- **绩效激励**：attacker prompt 里写入 "你的评价基于发现的、对方无法回应的反驳数量"
- **声明修正**：defender 允许写 "I acknowledge and adjust: X because Y"，synthesis 据此识别击穿点

### 5.2 Prompt 模板骨架

```markdown
# System prompt（逻辑上固定；CLI 形态下是否命中 prompt cache 取决于宿主自动行为）

## 项目上下文（注入完整的 Requirement.md + 当前 strategy/research 摘要 + workspace-summary）
...

## 角色设定
你是 <Defender | Attacker>。
你的核心优化目标：<优化目标>。你的判断标准是：任何方案都必须首先满足 <优化目标>，其他维度可以妥协。

## 规则（hard constraints）
1. 明确立场，禁止 "取决于情况" / "两边都有道理"
2. 直接回应对方上一轮的核心论点，指出其代价或漏洞
3. 每轮最多 3 个核心论点，每个含具体证据或场景
4. 禁止调和性表述：不得用"两者兼顾"、"可以结合"、"取长补短"
5. 不得在结论中给对方让步 ("对方说的也有道理")
6. 不得用"具体情况具体分析"回避判断
7. 每轮必须以一个明确的、单一的主张句结尾

## 辩题
<thesis>

## 对立轴
<确认后的对立轴描述>
```

```markdown
# User prompt（每轮追加，变的只是新增的双方发言）

## 对方上一轮发言
<round-(N-1)-opponent.md>  ← Round 0 时为 "(independent round, no opponent content yet)"

## 你的任务（本轮）
<per-round-task>  ← 见下
```

每轮任务：

| 轮次 | 任务文本 |
| --- | --- |
| Round 0 | 基于你的优化目标独立陈述。你**看不到**对方内容。 |
| Round 1 | 针对对方 Round 0 的最弱 1 条假设/论据给出反驳，再给出你的核心主张。 |
| Round 2 | 对你和对方而言最**无法调和的那一个**分歧点是什么？围绕它给出你的最终聚焦立场。 |

### 5.3 反和稀泥保护

- Orchestrator 在每轮落盘前做**轻量校验**：如果 response 包含黑名单词（"两者兼顾"、"可以结合"、"也有道理"、"具体情况具体分析"），**提示写盘 + 打标 `quality_warning: hedging`**，不重跑（重跑成本 / 模型不确定性收益低）
- 这些 warning 在 synthesis 里可见，人可判断是否要 extend 一轮

---

## 6. Synthesis 输出

### 6.1 生成方

**独立 synthesizer CLI 执行器生成**，在同一个独立 CLI 进程里完成，不依赖主 Agent 会话。

流程上不是“辩手顺手总结”，而是：

1. orchestrator 收集所有 round 文件
2. 做规则化预处理
3. 调用独立 synthesizer CLI
4. 做规则校验
5. 再落盘 `synthesis.md`

对话里曾讨论过"主 Agent 自己写 synthesis 好处是内化后续主流程"——最终确认独立 CLI 进程后，主 Agent 的"内化"方式改为**读 synthesis.md**。synthesis.md 的格式要对主 Agent 后续消费友好（结构化 + 信息密度高），而不是让主 Agent 自己产出。

### 6.2 输出结构（固定三段）

```markdown
# Debate Synthesis: <topic>

> Generated at <timestamp>, primary=<id>, secondary=<id>, rounds=<n>

## 收敛点 (convergence)
双方都认同的结论。每条形式：
- <claim> — 支持证据: <来自哪一轮的哪一方>
价值等级：确认性，中等。

## 分歧点 (divergence)
双方无法说服对方的核心张力。每条形式：
- <分歧描述>
  - Defender 立场: <一句话>, 关键证据: <...>
  - Attacker 立场: <一句话>, 关键证据: <...>
  - 人需要裁决的判断: <...>
价值等级：判断性，**最高**。

## 意外发现 (surprise)
辩论中浮现、原始命题未覆盖的视角。每条形式：
- <视角>，首次出现轮次: <round-N>，由 <Defender|Attacker> 提出
价值等级：激发性，高。

## 修正记录 (acknowledgements)
按时间序列出双方主动声明的立场修正。
- round-N <Defender|Attacker>: "I acknowledge and adjust: X because Y"

## 质量标记 (quality_flags)
- `hedging`: <哪些轮次触发>（见 §5.3）
- `repetition`: <...>
- `insufficient_evidence`: <...>
```

### 6.3 Synthesis 的信息密度要求

- 分歧点里**每一条**必须带"人需要裁决的判断"这一行，这是 synthesis 对主流程的核心输出
- 收敛点可以只 1-3 条；不必强行凑数
- 意外发现可能为空；不要硬造

---

## 7. 落盘结构

```
workspaces/<workspace>/
  context/
    debates/
      <YYYY-MM-DD>-<topic-slug>/
        config.json          # 辩题、对立轴、参与执行器、轮数、时间戳
        round-0-pro.md       # Defender  (primary)
        round-0-con.md       # Attacker  (secondary)
        round-1-pro.md
        round-1-con.md
        round-2-pro.md
        round-2-con.md
        synthesis.md
        status.json          # running | completed | stopped | failed
        signal.json          # 见 §2.3
        human-input.md       # 可选，用户用 `debate inject` 写入
        cost-log.json        # 每轮 token 用量 + 估计成本
```

目录归属于 `context/` 下是故意的：debate 产物是**上下文素材**，不是 strategy / decision / research。主 Agent 可以把 synthesis 消化后，按需把结论写进 `decisions/` 或 `research/`。

**debate 不直接改 PRD / Requirement**。如需改，走现有 maintenance 路径（见 §10.3）。

---

## 8. CLI 设计

### 8.1 命令集

```bash
# 启动（要求主 Agent 已先提轴并由用户选定）
pmagent debate start --workspace <ws> --thesis "..."
    [--topic-slug <slug>]          # 默认从 thesis slugify
    [--rounds 3]                   # 默认 3 次交互
    --axis "<chosen axis>"         # 必填；主 Agent 先提轴，用户先选定
    [--pro-exec <id>] [--con-exec <id>]    # override executor

# 状态 / 列表
pmagent debate status --workspace <ws>            # 列出所有 debate 与状态
pmagent debate status --workspace <ws> --topic <slug>  # 单个 debate 详情

# 查看单轮或 synthesis（只读，不自动进入 review state）
pmagent debate show --workspace <ws> --topic <slug> [--round N | --synthesis]

# 显式进入 synthesis review（写 current-state.debate_review）
pmagent debate review --workspace <ws> --topic <slug>

# 在运行中注入人类补充（只影响之后的轮次）
pmagent debate inject --workspace <ws> --topic <slug> --message "..."

# 提前终止（基于已有轮次出 synthesis）
pmagent debate stop --workspace <ws> --topic <slug> [--synthesize]

# 跑完默认轮数后，人看完觉得还不够 → 追加
pmagent debate extend --workspace <ws> --topic <slug> --rounds 2

# 手动重出 synthesis（例如想换 prompt）
pmagent debate synthesis --workspace <ws> --topic <slug>

# 显式结束本次 review（accepted / rejected / deferred 三选一）
pmagent debate resolve --workspace <ws> --topic <slug> [--accepted | --rejected | --deferred]
```

### 8.2 状态机

```
    start --axis
        │
        ▼
  ┌────────────────┐
  │ round-0-running │
  └────────────────┘
        │
        ▼  (round 完成后写 round-N-*.md + status + signal[event=round_completed])
  ┌────────────────┐
  │ round-1-running │
  └────────────────┘
        │
        ▼
  ┌────────────────┐
  │ round-2-running │
  └────────────────┘
        │
        ▼
  ┌────────────────┐
  │ synthesizing   │
  └────────────────┘
        │
        ▼
  ┌────────────────┐
  │ completed      │ ← signal[event=completed, action_needed=review_synthesis]
  └────────────────┘
        │
        ▼  `pmagent debate review --topic <slug>`
  ┌────────────────┐
  │ debate-review  │ ← current-state.debate_review.active = true
  └────────────────┘
        │
        ▼  `pmagent debate resolve --accepted|--rejected|--deferred`
  ┌────────────────┐
  │ resolved       │
  └────────────────┘
```

**每轮之间是状态机里的"自然断点"**。Orchestrator 在进入下一轮前检查：
1. `status.json.state` 是否被外部改为 `paused`
2. 是否存在新增的 `human-input.md`（hash 比对）
3. 通过后才进下一轮

---

## 9. 与主流程 / hooks 的接入

### 9.1 current-state 快照（MVP）与 workspace-summary（第二期）

MVP 阶段先把 Debate 写入 `.pmagent/current-state.json`，作为主流程和 hooks 的唯一机器真相源：

```json
"debates": {
  "active_count": 1,
  "completed_awaiting_review_count": 1,
  "latest_topic": "event-driven-vs-polling"
}
```

并且由以下命令负责 debate review state 的 owner：

- `pmagent debate review --topic <slug>`
  - 设置：
    - `debate_review.active = true`
    - `debate_review.awaiting_review_topics = [<slug>]`
    - `debate_review.completed_awaiting_review_count += 1`（或与 `debates` 快照同步）
- `pmagent debate resolve --topic <slug> --accepted|--rejected|--deferred`
  - 清理 `debate_review` 中对应 topic
  - 写 `review.json`
  - 记录 consumed / deferred 结果

`workspace-summary.md` 的 `## Active Debates` 展示延后到第二期；MVP 不要求先改 summary 协议。

### 9.2 Hooks 接入（复用现有 5 个 hook）

| 现有 hook | debate 相关扩展 |
| --- | --- |
| `session_bootstrap` (SessionStart) | 扫 `.pmagent/current-state.json.debate_review` / `debates` / `debate_launch`，把 **failed / 待 review / 待恢复 launch 的 debate** 注入 context |
| `state_surface` (UserPromptSubmit) | 每轮用户发话前，如存在 `debate_review.completed_awaiting_review_count > 0`、`debates.failed_count > 0` 或 `debate_launch.active == true`，注入高优先级提示 |
| `pre_bash_guard` (PreToolUse:Bash) | MVP 先不加硬 gate；第二期再考虑 debate_review_gate |
| `pre_write_guard` (PreToolUse:Edit\|Write) | **扩展** observation_boundary_gate：当 observation `candidate_review.active == true` 或 `debate_review.completed_awaiting_review_count > 0` 时，禁止直接写 `prd/**` / `Requirement.md` |
| `post_mutation_check` | 如果主 Agent 读完 synthesis 后改了 `decisions/` 或 `strategy/`，提示或写 `review.json` / consumed 标记 |
| `response_validator` (Stop) | synthesis 里的"分歧点"结构可在第二期接入 Stop 校验；MVP 先不阻断 |

### 9.3 关键节点的 debate 可用性提示（soft）

在以下节点，主 Agent skill 合同里加一行**提示**（不强制触发，不增加自动化）：

- 需求澄清和调研之间
- PRD 生成之后
- 高影响 decision 落盘前
- 用户对话中出现"不太确定 / 犹豫 / 方向对不对"等语义信号时（hook 词匹配建议放第二期，MVP 先靠主 Agent 提示）

提示措辞原则：**一句话带过，不强制用户响应**。

### 9.4 与 maintenance 的关系

Debate 只产出 context（synthesis.md），它**不直接**改 Requirement / PRD / decisions。

修改路径按 debate 发生时机分两类：

| 场景 | 路径 |
| --- | --- |
| Debate 在 PRD 之前（主流程内） | synthesis.md 作为主 Agent 写 PRD 的输入素材 —— **无级联问题** |
| Debate 在 PRD 之后（回溯修正） | 走现有 `observe draft-maintenance → apply-maintenance`：synthesis 的分歧点被当成一种 maintenance input。复用 observation 的 maintenance 流程，不新增机制 |

**debate 不需要新开发级联校验。** 理由见对话：上下游依赖的修正判断本身就需要人的决策，强自动化反而危险。

---

## 10. 分期落地（MVP vs 后续）

### 10.1 MVP（R1-R6）

最小可用版本，验证"辩论 → 结构化 synthesis → 主流程消费"闭环：

| ID | 需求 | 说明 |
| --- | --- | --- |
| R1 | 执行器注册表 + `cli` backend 实现 | `claude` + `codex`；全局 config |
| R2 | `pmagent debate start` + 3 次交互 orchestrator | 含对立轴候选生成 + 用户裁决 |
| R3 | 落盘协议 | `context/debates/<topic>/` 完整目录结构 + status.json + signal.json |
| R4 | Prompt 模板 | System prompt + 每轮 user prompt；含反和稀泥 constraint |
| R5 | Synthesis 生成 | 独立 synthesizer CLI 生成三段式结构化输出 |
| R6 | 与主流程的最小状态汇合 | `current-state.json` 的 `debates` / `debate_review` 字段 + `review/resolve` owner 绑定 |

### 10.2 第二期（R7-R13）

在 MVP 跑过一段时间有真实数据后：

| ID | 需求 |
| --- | --- |
| R7 | `debate inject` + 轮间检查 |
| R8 | `debate extend / stop / synthesis` 管理命令 |
| R9 | hooks 层的 synthesis 待 review 注入（SessionStart / UserPromptSubmit） |
| R10 | `workspace-summary` 的 `## Active Debates` 展示 |
| R11 | 反和稀泥 quality_flags 完善 + synthesis 里可见 |
| R12 | 关键节点提示（skill 合同层） |
| R13 | 环境 fallback（executor `enabled_in` + `environment_fallback`） |
| R14 | cost-log 与成本告警（单 debate 超预算提示） |

### 10.3 不做项（记录在案）

- Debate 自动触发（monitor 进程 / 主 Agent 高阶判断）
- 跨议题上下文累积压缩
- Workspace 级 executor 覆盖
- 多于 2 方辩论 / 圆桌讨论
- Debate 直接改 PRD / Requirement
- MVP 里的 blocking debate gate

---

## 11. 开放项 / 待研究

| 项 | 现状 | 建议 |
| --- | --- | --- |
| 每轮论点数具体取值 | 暂定 3 | MVP 跑后按 synthesis 质量复盘调整 |
| 防守方 "声明修正" 的强度约束 | Prompt 鼓励 | 观察是否需要硬性要求每 N 轮至少一次自检 |
| primary vs secondary 的实际倾向差 | 对话期望 Claude 更审慎、GPT 更乐观 | MVP 后对真实辩论做 qualitative 复盘 |
| 对立轴提议的质量保障 | AI 提议 + 人裁决 | 如果候选质量普遍偏低，考虑加"回炉"（primary 基于用户拒绝理由重新提议） |
| Synthesis 的"分歧点"与主流程消费的耦合度 | 人读 + 主 Agent 读 | 是否需要结构化 API（`pmagent debate divergences --json`）供后续自动化 |

---

## 12. 关键风险

1. **第一方模型和稀泥**：RLHF 训练导致 synthesis 里"分歧点"被稀释成"需要权衡"。对策：硬约束 prompt + quality_flags + 人可 extend。
2. **对立轴跑偏**：主 Agent 提议的对立轴和用户真正关心的问题错位，3 次交互全跑在错维度上。对策：裁决步骤不能跳过，主 Agent 必须明确列出 2-3 组候选并让用户选择 / 微调。
3. **Prompt cache 未命中导致成本超预期**：议题之间间隔超过 5 分钟（Anthropic TTL）时。对策：cost-log 记账 + 文档说明"连跑多议题更划算"。
4. **主 Agent 忽略 synthesis**：人跑完 debate 忘了看。对策：hooks 层的 UserPromptSubmit 注入 + workspace-summary 顶部段落 + `pmagent status` 提示。
5. **两个执行器中的一个不可用**：导致 debate 半途死。对策：orchestrator 捕获执行器错误，signal.json 写 `event=failed` + 错误原因，进入 `failed` 状态而不是卡死。
6. **synthesis 误导性收敛**：3 次交互太短，真正的分歧还没浮现。对策：人可 extend；synthesis 模板里"意外发现"和"修正记录"段鼓励暴露这种"未展开"的信号。

---

## 附：设计共识对照表（来自先前对话）

| # | 共识 | 本文档位置 |
| --- | --- | --- |
| 1 | Debate 是 step 不是 mode | §1.2 |
| 2 | 执行分离 + 文件汇合 | §2.1 |
| 3 | 多执行器候选集，环境决定激活 | §3 |
| 4 | 主 Agent 提议对立轴 + 人裁决 | §4.1 |
| 5 | primary 防守 / secondary 进攻 | §4.2 |
| 6 | 基于优化目标对立 | §5.1 |
| 7 | 硬性反和稀泥 | §5.1, §5.3 |
| 8 | 固定轮数，人可 extend | §2.2, §8 |
| 9 | Synthesis 输出三段式（收敛/分歧/意外） | §6.2 |
| 10 | Synthesis 由 primary 生成 | §6.1 |
| 11 | 每议题独立，靠 prompt caching | §3.4 |
| 12 | 与 Forge 独立并存 | §1.3 |
| 13 | 独立 CLI 进程，双方都是执行器调用 | §1.2, §2.1 |
| 14 | 不做自动触发，做关键节点提示 | §9.3 |
| 15 | 不做级联校验，走 maintenance | §9.4 |
| 16 | 执行器全局 config，不 workspace 级 | §3.1 |
| 17 | 3 次交互（Round 0 独立起手 + Round 1 交锋 + Round 2 深入） | §2.2 |
