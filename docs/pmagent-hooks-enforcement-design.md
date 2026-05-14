# pmagent × Claude Code Hooks 强约束设计

## 文档定位

pmagent 本身是一个**嵌在外部 Agent 之上的工作流规范层**。它目前的约束分两层：

1. **CLI 内置的硬约束** —— 写在 Python 实现里，Agent 绕不过去。例如 `observe set-cadence/enable` 缺少 `--confirm-cadence` 会直接 `SystemExit`；`Requirement.md` 正文 CLI 完全不写。
2. **AGENTS.md / CLAUDE.md / skill.md 里的软约束** —— 只是提示外部 Agent "应该这样做"，Claude Code / Codex 可以读，但读不读、读完遵不遵守，取决于模型当下的注意力。

这份文档只讨论第二层：**哪些软约束可以借 Claude Code 的 hooks 机制变成强约束**、怎么做、以及哪些不适合变强。

> 配套文档：`docs/pmagent-workflow-with-hooks.md` —— 整条主链路上 hooks 的落点位置。

## Claude Code hooks 能力速查

| 事件 | 时机 | 能做什么 | 适用拦截 |
| --- | --- | --- | --- |
| `SessionStart` | 会话开始 | 注入上下文、执行命令、输出到 transcript | 强制读文件、预跑 audit、回显当前状态 |
| `UserPromptSubmit` | 用户每次发消息前 | 在用户 prompt 之前注入一段上下文；可阻断 | 每轮强制刷新 state、surface backlog |
| `PreToolUse` | 工具调用前（Bash / Edit / Write / Read ...） | exit code 2 阻断；可改写参数反馈 | 禁掉无 `--confirm-cadence` 的 cadence 变更、保护 Requirement.md 以外通道写入 |
| `PostToolUse` | 工具调用后 | 回读产物、校验、注入反馈 | summary_sync 校验、raw-log 追加校验 |
| `Stop` | Agent 一轮回答结束前 | 检查最终回复内容；可要求重说 | 评分对象必须带评分表、状态块 |
| `SubagentStop` | 子 Agent 结束 | 同 Stop | 子 Agent 回写质量校验 |
| `PreCompact` | 上下文压缩前 | 最后一次写盘 | 关键状态落盘、避免压缩后丢状态 |
| `SessionEnd` | 会话结束 | 清理 / 记录 | workspace-close 收尾检查 |

关键边界：hooks 在**外部 Agent 的进程里**跑，它们拦截的是 Agent 的工具调用，而不是 pmagent CLI 本身。也就是说，同一条规则如果放在 CLI 里已经能挡住（例如 cadence 确认），hooks 的价值是让 Agent 更早知道自己要做什么，而不是再挡一次。

## 软约束清单与 Hook 映射

### A. 建议落成强约束（高 ROI）

| 软约束来源 | 规则 | 推荐 Hook | 实施动作 | 阻断 / 提示 |
| --- | --- | --- | --- | --- |
| AGENTS.md §读取顺序 | 开工前必须按序读 `AGENTS.md` → `agent-workflow.yaml` → `projects.json` → `workspace-summary.md` | `SessionStart` | 直接把这几份文件拼成 context 注入，省掉"靠 Agent 自觉读" | 不阻断，确保必读内容进上下文 |
| AGENTS.md §会话规则 / `audit_gate` | active workspace 存在时，正式工作前必须 `pmagent observe audit --run-catch-up --json` | `SessionStart` + `UserPromptSubmit` | 由 hook 直接调用并把 JSON 注入 context | 不阻断；把结果直接喂给 Agent |
| `backlog_visibility_gate` | 有未读 observation 必须先 surface | `UserPromptSubmit` | 跑 `pmagent observe unread --workspace <ws> --json`，如有 backlog 就在 prompt 前加 system-reminder | 非空时强制注入红字提示 |
|                                                 |                                                              |                                                              |                                                              |                              |
| `review_gate` | observation accept/reject/snooze 需要用户确认 | `PreToolUse`（Bash） | 拦截 `pmagent observe (accept|reject|snooze)`，检查当轮 transcript 里是否出现用户确认标记；否则 exit 2 要求先确认 | 阻断 |
| `observation_boundary_gate` | Observation 不直接改 PRD | `PreToolUse`（Edit / Write） | 目标路径命中 `workspaces/*/prd/**` 时，若当前 step 状态是 `candidate-review`，则阻断 | 阻断 |
| `summary_sync_gate` | `workspace-summary.md` 与 `.pmagent/current-state.json` 必须同步 | `PostToolUse`（Edit / Write，路径 = `workspace-summary.md`） | 校验 `current-state.json.updated_at` 是否 ≥ 编辑时间戳，不是则写一条 system-reminder 让 Agent 立即补 | 非阻断提示 |
|                                                 |                                                              |                                                              |                                                              |                              |
| Phase Raw Logging Rule | clarifying / research 必须把原始问答落到 `context/clarifying-log.md` / `research/research-log.md` | `PostToolUse`（Bash，命令匹配 `pmagent clarify answer` / `pmagent research note`） | 校验对应 log 文件 mtime 是否更新；没有则提示 Agent 补 append | 非阻断提示 |
| State-First Execution Rule / `state_first_gate` | 推进 phase 前必须刷新 state | `UserPromptSubmit` | 自动跑 `pmagent status --json` 并把简化后的状态块注入；Agent 不需要再手动跑 | 非阻断，保证状态新鲜 |
| Score Visibility Contract / Depth Retention | 引用了 score-bearing object 的最终回复必须渲染评分表 | `Stop` | 扫描最近一轮 tool 结果是否出现 `"readiness"` / `"scores"` / `"dimensions"` 等字段，若 Agent 最终回答里没有对应 markdown 表，则 exit 2 让 Agent 重说 | 阻断回复，要求重出 |

### B. 可做但收益一般（按需再上）

| 软约束 | 推荐 Hook | 备注 |
| --- | --- | --- |
| "不要静默推进 workflow；先回显状态，再执行" | `Stop` | 要能判断 Agent 是否"静默推进"比较主观，容易误伤 |
| Phase-End Pressure Pass Rule | `PreToolUse`（拦截 `pmagent prd init-draft`） | 可以强制要求 clarifying/researching 的 pressure pass 产物存在，但"产物"形态不统一，难度中等 |
| Agent Questioning Rule："不要问自己能查到的事" | `UserPromptSubmit` | 只能做弱提示，无法强判断 |
| Observation Policy Rule：至少两次显式询问 | `PreToolUse`（拦截 `pmagent prd init-draft`） | 若 `observation.decision_status == unresolved` 且将进入 PRD，阻断并提醒 | 可做 |

### C. 不建议 hook 化

这些规则本质是**语义判断**或**会话叙事**，交给 Agent 做更合适：

- Recommended Practices 里的"正式回复里加状态块" —— 模板有用，硬卡容易产生很多虚假合规的噪音回复。
- Questioning Boundary —— "别对用户说现在在补 scope/intent/outcome"。这是前台语言风格要求，用 Stop 去扫关键词会误伤。
- Phase-End Pressure Pass Rule 的具体形式（追问 tradeoff / 质疑前提 / 反向视角）—— 没有稳定的机器可读信号。
- Clarifying / Research Scoring Rule 里"评分由 Agent 判断"—— Agent 本身的语义能力需要，hook 不是合适载体。

## 推荐的 settings.json 骨架（示意，不直接写入）

以下展示 A 类核心 hook 的形态，实际落地时再按平台（win32 用 `bash.exe -lc` 或 `powershell -Command`）调整：

```jsonc
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python -m pmagent.hooks.session_bootstrap",
            "timeout_ms": 8000
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python -m pmagent.hooks.state_surface" }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python -m pmagent.hooks.pre_bash_guard" }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python -m pmagent.hooks.pre_write_guard" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash|Edit|Write",
        "hooks": [
          { "type": "command", "command": "python -m pmagent.hooks.post_mutation_check" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "python -m pmagent.hooks.response_validator" }
        ]
      }
    ]
  }
}
```

建议所有 hook 逻辑都收敛到 `src/pmagent/hooks/` 一个子包里，和 CLI 共用 paths / current_state / observation 读取代码，避免重复实现。

## 各 Hook 详细设计

### 1. `SessionStart` — 读取顺序 & audit_gate

职责：
- 读 `config/projects.json`，解析 `active_project` / `active_workspace`。
- 若 active workspace 存在：
  - 读取 `workspace-summary.md` 和 `.pmagent/current-state.json`，拼进 system context。
  - 跑 `pmagent observe audit --workspace <ws> --run-catch-up --json`，把结果注入。
  - 读取 `AGENTS.md` + `config/agent-workflow.yaml` 的摘要片段。
- 没有 active workspace：只注入"当前无激活 workspace"的提示和 `pmagent status` 引导。

失败行为：audit 失败就把错误文本也注入，别静默吞。

### 2. `UserPromptSubmit` — state_first + backlog_visibility

每次用户发话前：
- `pmagent status --json` → 取 `phase / active_step / next_recommended_step`，注入状态块。
- `pmagent observe unread --workspace <ws> --json` → 非空时注入：
  ```
  ⚠️ backlog: 有 N 条未读 observation，按 AGENTS.md 规定应先 candidate-review 再推进主线。
  ```
- 成本敏感：hook 要有超时（≤ 1.5s），超时就放行，不能卡用户输入。

### 3. `PreToolUse`(Bash) — cadence / review / requirement-authorship / workspace-close

读取 Bash 工具参数 `command`，做命令级正则匹配：

| 命中 | 检查 | 动作 |
| --- | --- | --- |
| `pmagent observe (enable\|set-cadence\|init-workspace)` 且 cadence 非 `manual` 且无 `--confirm-cadence` | 缺参 | exit 2 + "需要 --confirm-cadence" |
| `pmagent observe (accept\|reject\|snooze)` | 会话 transcript 无 `review_confirmed: true` 标记 | exit 2 + "请先让用户明确 accept/reject/snooze" |
| `pmagent workspace-close` | 当前 state phase != `maintaining` 且无 `exports/latest` | exit 2 + "workspace-close 只在本轮工作真正收束时执行" |
| CLI 命令试图修改 `Requirement.md` 正文 | 参数命中 | exit 2（兜底；CLI 已拒，但给更早反馈） |

### 4. `PreToolUse`(Edit|Write) — observation_boundary_gate

- 若 `.pmagent/current-state.json.active_step == 'candidate-review'`，且写入路径匹配 `workspaces/*/prd/**`，exit 2 并提示 "observation 不直接改 PRD，请走 draft-maintenance → apply-maintenance"。

### 5. `PostToolUse` — summary_sync + phase-raw-log

两类触发：

**summary_sync_gate**：`Edit|Write` 路径 = `workspace-summary.md`  
→ 读 `.pmagent/current-state.json` mtime；若旧于 summary 的 mtime 超过阈值（例如 10s），注入 system-reminder：
```
⚠️ summary_sync_gate: workspace-summary.md 已更新但 .pmagent/current-state.json 尚未刷新，请调用对应 CLI 同步。
```

**phase_raw_logging**：Bash 命中 `pmagent clarify answer` / `pmagent research note`  
→ 比较 `context/clarifying-log.md` / `research/research-log.md` 的 mtime 是否发生变化。没变就提示 Agent 立刻追加原始内容。

### 6. `Stop` — Score Visibility + Depth Retention

扫描本轮所有 tool result，若出现评分对象特征字段（`"readiness"` / `"dimensions"` / `"blocking_gates"` 等），则：
- 读最终 assistant 文本。
- 若不含 markdown 表（`|---|---|`）或 `dimensions` 对应的所有键值没全渲染，exit 2 要求重写。
- 若表已出，但文本不足某阈值（衡量 depth retention），注入提示但不阻断。

实现上需要一个稳定的 parser，可以复用 `presentation.py` 已有的 rendering 逻辑。

## 不适合 Hook 化的约束（再强调）

- **语言风格类**：Questioning Boundary / Recommended Practices —— 用 Stop 扫关键词会产生大量误伤。
- **语义判断类**：Clarifying/Research scoring、observation-to-PRD 映射判断 —— 这是 Agent 的核心能力，不该被机器替代或否决。
- **节奏建议类**：Phase-End Pressure Pass 的具体玩法 —— 没有稳定信号。

这些仍然留在 AGENTS.md / skill.md，用软约束 + 模型训练分布去贴近。

## 风险与注意事项

1. **超时**：hooks 是同步阻塞用户体验的。每个 hook 必须有毫秒级超时兜底，超时静默放行。
2. **跨平台**：pmagent 默认支持 win32 / macOS / Linux。hooks 全部用 `python -m pmagent.hooks.*` 入口，避开 shell 差异。
3. **与 CLI 真相源顺序一致**：hooks 读的状态必须来自 `.pmagent/current-state.json` 和 `config/projects.json`，不允许自己重新推断当前 phase。
4. **可关**：所有 hooks 由用户在 `.claude/settings.json` / `settings.local.json` 里显式启用；pmagent 不要自动下发，避免脚本劫持争议。建议额外提供 `pmagent hooks install --scope local` 命令生成推荐配置。
5. **幂等**：hooks 产生的 system-reminder 要避免重复噪音，必要时用 `.pmagent/hooks-state.json` 记录已提示过的 gate。
6. **与 memory 的边界**：hook 不要写 `~/.claude/.../memory/`；那是 Claude Code harness 的领地。pmagent 自己的状态只写 `data_dir` 里。

## 后续工作建议

1. 落 `src/pmagent/hooks/` 子包，只实现 A 类五个 hook 入口。
2. 新增 `pmagent hooks install / uninstall / doctor` 命令，负责写入 `.claude/settings.json` 的 hooks 段并做健康检查。
3. 在 `config/agent-workflow.yaml` 增加 `hooks:` 节，把"哪些 gate 由 hook 强约束"这件事也结构化。
4. 在 AGENTS.md 顶部加一句："以下规则可能被 hook 强制拦截，违反将直接被阻断。" 让软约束和强约束可区分。
5. 给 `tests/` 加一组 hook-level 的契约测试（mock transcript + state），保证升级不破坏约束。

## 附：软约束 → 约束层级对照表

| 规则 | 当前位置 | 当前层级 | 拟新层级 |
| --- | --- | --- | --- |
| 读取顺序 | AGENTS.md | soft | SessionStart hard |
| audit_gate | AGENTS.md + CLAUDE.md | soft | SessionStart + UserPromptSubmit hard |
| review_gate | AGENTS.md | soft | PreToolUse hard |
| cadence_gate | CLI + AGENTS.md | CLI hard + soft | CLI hard + PreToolUse hard |
| maintenance_gate | AGENTS.md + CLI | CLI hard + soft | 维持 |
| observation_boundary_gate | AGENTS.md | soft | PreToolUse(Edit/Write) hard |
| summary_sync_gate | AGENTS.md | soft | PostToolUse 校验 |
| requirement_authorship_gate | CLI + AGENTS.md | CLI hard + soft | 维持 + PreToolUse 兜底 |
| state_first_gate | AGENTS.md | soft | UserPromptSubmit hard |
| backlog_visibility_gate | AGENTS.md | soft | UserPromptSubmit hard |
| scoring_conservatism_gate | AGENTS.md | soft | 维持 soft |
| Score Visibility / Depth Retention | AGENTS.md | soft | Stop hard（可阻断重写） |
| Phase Raw Logging | AGENTS.md | soft | PostToolUse 提示 |
| Observation Policy 两次显式询问 | AGENTS.md | soft | PreToolUse(prd init-draft) 建议硬拦 |
