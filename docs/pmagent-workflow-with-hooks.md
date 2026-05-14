# pmagent 主链路 × Hooks 落点

## 文档定位

这份文档把 pmagent 的端到端工作链路画出来，并在每个环节上标注 Claude Code hooks 的**触发位置**与**职责**。

- 只关心"会话级"链路：一次 Claude Code / Codex 会话从打开到收尾。
- hook 的设计理由和映射表见 `docs/pmagent-hooks-enforcement-design.md`；本文只做"在哪里触发"。
- CLI 自身的内置约束不在 hook 体系内，仅标注用于对照。

使用到的符号：

- 🪝 hook 触发点（方括号内为事件名）
- 🧠 Agent 侧动作（Claude Code / Codex 的工作）
- ⚙️ pmagent CLI 调用
- 🗂 产物 / 状态文件
- ⛔ 可阻断（hook exit 2 / CLI SystemExit）

## 端到端流程骨架

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 0. 首次安装                                                               │
│    ⚙️ pmagent init --dir <data_dir>                                       │
│    🗂 <data_dir>/ 下生成 AGENTS.md / CLAUDE.md / config/ / skills/ ...    │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. 会话开始                                                               │
│    🪝 [SessionStart]                                                      │
│       - 读 AGENTS.md / agent-workflow.yaml / projects.json               │
│       - 读 active workspace 的 workspace-summary + current-state         │
│       - 自动跑 observe audit --run-catch-up --json 并注入                 │
│    🧠 Agent 得到完整上下文，回显 mode / phase / next step                 │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. 每一轮用户发话前                                                       │
│    🪝 [UserPromptSubmit]                                                  │
│       - pmagent status --json → 注入 state block                         │
│       - observe unread --json → 有 backlog 就红字提示                     │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. 无 workspace → start / workspace-init                                  │
│    🧠 Agent 解析用户意图，选 mode (zero-to-one / conviction-forge)        │
│    ⚙️ pmagent start 或 workspace-init --project --workspace              │
│    🗂 workspaces/<ws>/Requirement.md 骨架 + .pmagent/current-state.json  │
│    🪝 [PreToolUse:Bash] — workspace-init 携带非 manual cadence           │
│       时必须 --confirm-cadence，否则 ⛔                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. Observation 策略询问 (节点 1)                                          │
│    🧠 按 AGENTS.md §Observation Policy Rule 询问是否开启 + cadence        │
│    ⚙️ pmagent observe enable/set-cadence --confirm-cadence               │
│    🪝 [PreToolUse:Bash] — cadence_gate，缺 --confirm-cadence ⛔            │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. clarifying 阶段                                                        │
│    ⚙️ pmagent clarify status / clarify answer                            │
│    🗂 context/clarifying-log.md  ← 全量原始问答                           │
│    🗂 Requirement.md             ← Agent 直接编辑，CLI 不写               │
│    🪝 [PostToolUse:Bash] — clarify answer 后校验 clarifying-log mtime     │
│       未更新则提示追加原始问答                                             │
│    🪝 [PreToolUse:Edit|Write] — requirement_authorship_gate：保护         │
│       Requirement.md 不被非 Agent 通道写入                                │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. Phase-End pressure pass (soft)                                         │
│    🧠 Agent 回头挑战边界 / 非目标 / decision boundaries                    │
│    ⚙️ pmagent clarify set-scores --patch-file ...                        │
│    🪝 [Stop] — 回答若引用 readiness 且无评分表 ⛔ 要求重出                  │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 7. researching 阶段                                                       │
│    ⚙️ pmagent research start / status / note                             │
│    🗂 research/research-log.md   ← 全量原始记录                           │
│    🪝 [PostToolUse:Bash] — research note 后校验 research-log mtime        │
│    🪝 [Stop] — 同上，评分对象回复必须带表                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 8. Observation 策略询问 (节点 2)                                          │
│    🧠 准备进入 PRD 前再询问一次（若 decision_status 仍 unresolved）         │
│    🪝 [PreToolUse:Bash] — 建议拦截 `pmagent prd init-draft` 当             │
│       observation.decision_status == unresolved 时 ⛔                     │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 9. PRD 阶段                                                               │
│    ⚙️ pmagent prd init-draft / prd review / prd challenge                │
│    🗂 prd/ 目录 + workspace-summary.md                                    │
│    🪝 [PreToolUse:Edit|Write] — observation_boundary_gate：当 active_step │
│       是 candidate-review 时禁止直接改 prd/**                              │
│    🪝 [PostToolUse:Edit|Write] — summary_sync_gate：写了                    │
│       workspace-summary.md 后校验 .pmagent/current-state.json 已刷新       │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 10. Observation 捕捉循环 (后台 / 按需)                                    │
│     ⚙️ pmagent observe run --project <project>                           │
│     🗂 observations/<project>/index.json / runs/*                        │
│     （由 scheduler / launchd / Task Scheduler 触发；不在单次会话内）       │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 11. 每次进入交互都先 audit  (已由 SessionStart / UserPromptSubmit 覆盖)    │
│     ⚙️ pmagent observe audit --workspace <ws> --run-catch-up --json      │
│     🪝 [SessionStart] + [UserPromptSubmit] — audit_gate                  │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 12. candidate-review step (resume-time)                                   │
│     🧠 对每条 unread observation，用户明确 accept / reject / snooze       │
│     ⚙️ pmagent observe accept|reject|snooze --card <id>                  │
│     🪝 [PreToolUse:Bash] — review_gate：当轮 transcript 无用户确认         │
│        标记则 ⛔                                                            │
│     🪝 [PreToolUse:Edit|Write] — observation_boundary_gate                │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 13. maintenance 阶段                                                      │
│     ⚙️ pmagent observe maintenance-status                                │
│     ⚙️ pmagent observe draft-maintenance  ← 生成草稿容器                  │
│     🧠 Agent 根据 accepted cards 决定如何改 PRD / Requirement / decisions │
│     ⚙️ pmagent observe apply-maintenance ← 只做 finalize / changelog      │
│     🪝 [PreToolUse:Bash] — maintenance_gate：CLI 已拒仅 inbox 进 draft     │
│     🪝 [PostToolUse:Edit|Write] — summary_sync_gate                      │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 14. 导出 Dev Pack                                                         │
│     ⚙️ pmagent export --project <project> --workspace <workspace>        │
│     🗂 workspaces/<ws>/exports/                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 15. workspace 收尾                                                        │
│     ⚙️ pmagent workspace-close --workspace <workspace>                    │
│     🗂 memory/global-candidates/<date>-<workspace>-global-promotion.md    │
│     🪝 [PreToolUse:Bash] — workspace-close 只在真正收束时允许，           │
│        phase != maintaining 或无 exports 则 ⛔                             │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 16. 会话结束                                                              │
│     🪝 [SessionEnd] — 写 .pmagent/hooks-state.json，做清理                 │
│     🪝 [PreCompact] — 关键状态兜底落盘（防压缩丢状态）                     │
└─────────────────────────────────────────────────────────────────────────┘
```

## 贯穿全程的 hooks（每轮都响应）

| Hook | 触发频率 | 主要职责 | 阻断？ |
| --- | --- | --- | --- |
| `SessionStart` | 会话启动 1 次 | 强制读取顺序、注入 workspace context、预跑 audit | 否 |
| `UserPromptSubmit` | 每轮用户发话前 | 刷新 state block、surface backlog | 否 |
| `PreToolUse:Bash` | 每条 Bash 调用前 | cadence / review / workspace-close / requirement-authorship gate | 是 |
| `PreToolUse:Edit\|Write` | 每次文件改动前 | observation_boundary_gate、requirement_authorship 兜底 | 是 |
| `PostToolUse:Bash` | 每条 Bash 调用后 | phase-raw-log 校验 | 否（提示） |
| `PostToolUse:Edit\|Write` | 每次文件改动后 | summary_sync_gate | 否（提示） |
| `Stop` | Agent 一轮结束前 | Score Visibility & Depth Retention | 是 |
| `SessionEnd` | 会话结束 | 状态兜底、清理 | 否 |
| `PreCompact` | 上下文压缩前 | 关键状态落盘 | 否 |

## 按阶段查表

如果只想知道某个阶段上会碰到哪些 hook：

| 阶段 | hooks |
| --- | --- |
| 安装 / init | — |
| 会话启动 | `SessionStart` |
| 每轮发话 | `UserPromptSubmit` |
| start / workspace-init | `PreToolUse:Bash`（cadence_gate） |
| observation 开关 / cadence | `PreToolUse:Bash`（cadence_gate） |
| clarifying | `PostToolUse:Bash`（raw-log）、`PreToolUse:Edit\|Write`（requirement authorship 兜底）、`Stop` |
| researching | `PostToolUse:Bash`（raw-log）、`Stop` |
| 进入 PRD 前 | `PreToolUse:Bash`（observation policy 节点 2） |
| PRD 编辑 | `PreToolUse:Edit\|Write`（observation_boundary_gate）、`PostToolUse:Edit\|Write`（summary_sync_gate） |
| observe run / audit | 由 `SessionStart` / `UserPromptSubmit` 自动拉起 |
| candidate-review | `PreToolUse:Bash`（review_gate）、`PreToolUse:Edit\|Write`（observation_boundary_gate） |
| maintenance | `PostToolUse:Edit\|Write`（summary_sync_gate）、`Stop` |
| export | — |
| workspace-close | `PreToolUse:Bash`（workspace-close 合法性） |
| 会话结束 | `SessionEnd`、`PreCompact` |

## 状态真相源 vs. Hook 动作

| 层 | 文件 | 是谁写 | hook 用法 |
| --- | --- | --- | --- |
| 机器状态 | `.pmagent/current-state.json` | CLI | hook 只读，用来判断是否允许某动作 |
| 压缩摘要 | `workspace-summary.md` | Agent 写 + CLI 辅助 | `PostToolUse` 校验同步 |
| 稳定共识 | `Requirement.md` | Agent 直接写 | `PreToolUse` 保护不被 CLI / 错工具覆盖 |
| 原始日志 | `context/clarifying-log.md` / `research/research-log.md` | Agent append | `PostToolUse` 校验 mtime |
| 观测流 | `observations/<project>/index.json` / `state.json` | CLI + scheduler | hook 只读，用来 surface backlog |
| 项目注册 | `config/projects.json` | CLI | hook 用来识别 active workspace |

## 与 `agent-workflow.yaml` 的对应

建议 `agent-workflow.yaml` 新增一个 `hooks:` 顶级节，声明"哪些 gate 现在是 hook 强约束"。例如：

```yaml
hooks:
  session_start:
    enforce:
      - read_order
      - audit_gate
  user_prompt_submit:
    enforce:
      - state_first_gate
      - backlog_visibility_gate
  pre_tool_use_bash:
    enforce:
      - cadence_gate
      - review_gate
      - workspace_close_discipline
      - requirement_authorship_fallback
  pre_tool_use_write:
    enforce:
      - observation_boundary_gate
  post_tool_use:
    enforce:
      - summary_sync_gate
      - phase_raw_logging
  stop:
    enforce:
      - score_visibility
      - depth_retention
```

这样 AGENTS.md 里每条 gate 都可以标注"由 hook 强制" / "由 CLI 强制" / "保持软约束"，Agent 读 AGENTS.md 时就知道哪些会被拦。

## 下一步动作建议

1. 根据 `docs/pmagent-hooks-enforcement-design.md` 的"A 类 hook"先行实现。
2. 建 `src/pmagent/hooks/` 子包，暴露 `python -m pmagent.hooks.<name>` CLI 入口。
3. 增加 `pmagent hooks install/uninstall/doctor` 子命令生成 `.claude/settings.json` 的 hooks 段。
4. `agent-workflow.yaml` 加 `hooks:` 节，`AGENTS.md` 标注每条规则的执行层级。
5. 给 A 类 hook 补契约测试，保证跨平台行为一致。
