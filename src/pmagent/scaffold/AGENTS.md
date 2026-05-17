<!-- PMAGENT:VERSION:0.1.0 -->

<!-- PMAGENT:MANAGED:BEGIN -->

# PM Agent

## 文档定位

你正在 `pmagent init --dir <data_dir>` 生成的 PM Data 目录中工作。
PMAgent 源码仓库只是 CLI / scaffold，不承载项目主链路规范。

- `config/agent-workflow.yaml` 是机器可读执行合同
- `AGENTS.md` 是 host-agnostic 协作摘要
- 同一规则冲突时，以 `config/agent-workflow.yaml` 为准

## 读取顺序

开始正式工作前，按以下顺序读取：

1. `AGENTS.md`
2. `config/agent-workflow.yaml`
3. `config/projects.json`
4. 当存在 active workspace 时，读取 `workspaces/<workspace>/workspace-summary.md`
5. 仅在需要时再深入读取：
   - `Requirement.md`
   - `research/`
   - `context/`
   - `decisions/`
   - `prd/`

## 真相源优先级

1. 项目内容：当前 PM Data 目录的本地 Git
2. 运行行为：PMAgent CLI / Python implementation
3. 结构化合同：`config/agent-workflow.yaml`
4. 协作摘要：`AGENTS.md`
5. 运行时状态文件：`config/projects.json`、project / workspace state、`workspace-summary.md`、`observations/<project>/index.json|policy.json|state.json`

## 目录与资产边界

- project 级长期资产写入 `projects/<project>/`
- workspace 级当前工作资产写入 `workspaces/<workspace>/`
- project 级 observation 信号流写入 `observations/<project>/`
- `context/clarifying-log.md` 是 clarifying 阶段的**全量原始问答日志**
- `research/research-log.md` 是 researching 阶段的**全量原始记录日志**
- `context/debates/` 保存 Debate 的 round / synthesis / review 工件；它们属于 context artifact，不是 canonical decision
- `workspace-summary.md` 是压缩语义入口
- `.pmagent/current-state.json` 是结构化机器状态入口
- `candidate-review` 是 session review step，不是 mode
- `debate-review` 是与 `candidate-review` 并行的 review surface，不占用 `active_step` / `pending_user_decision` 的单槽位
- `debate-launch` 是 executor precheck 失败后的待恢复启动状态，写在 `.pmagent/current-state.json.debate_launch`
- `workspace-close` 是正式生命周期动作，只在本轮工作真正收束时执行

## 主链路与 Skill

- PM Data 主链路只用本地 `skills/steps/*/skill.md` 与 `config/agent-workflow.yaml` 声明的 PMAgent workflow skill。
- 禁止把 `$deep-interview`、`$plan`、`$ralplan`、`$autopilot`、`$ralph`、`$team` 写入 `recommended_skills`、状态块或下一步命令；它们不能替代 `write-requirement`、`do-research`、`write-prd`、`dev-readiness`、`observe`、`infra`。
- 新需求按 `workspace-init -> status|route -> clarify -> write-requirement -> do-research -> write-prd` 推进；readiness 只导航，不锁流程。
- 全局 Codex/OMX skill 只可作为用户显式要求的“外部辅助”；结论必须回写 PMAgent artifacts，且不得写成 PMAgent 推荐 skill。
- 正式推进前回显 `phase/active_step`、`recommended_skills`、选择原因和下一步命令。

## 会话规则

- 当存在 active workspace 时，正式工作前先执行 `pmagent observe audit --workspace <workspace> --run-catch-up --json`；该入口会优先从 Feishu Base 拉取 Candidate Cards 并刷新 review 状态。
- `candidate-review` 的主来源是 `workspaces/<workspace>/candidate-updates/inbox/*.md`；`observations/<project>/index.json` 只作为 legacy/local-only 兼容来源。
- 如果存在待审 Candidate Card 或 legacy unread observation，先显式告知用户，再进入 `candidate-review`。
- 如果 `.pmagent/current-state.json` 中存在 debate failed / pending review / pending launch，先显式 surface 再继续普通流程；优先使用 `pmagent start|resume|next|review --json` 或 hooks 注入结果作为前台入口
- 当当前目录是 `jj` 仓库时，再运行 `jj status`；需要时运行 `jj diff --git`
- 不要静默推进 workflow；先回显状态，再执行

## 飞书同步规则

- 本地 PM Data Git 是真相源；Feishu Wiki 是 Markdown 镜像，Feishu Base 是 Candidate Card 中转。
- 首次配置飞书应用时，先跑 `pmagent infra auth-guide --brand lark --app-id <approved-app-id>` 生成最小权限授权命令；不要直接无 scope 执行 `lark-cli auth login`，避免申请全量权限。
- 改动人可读白名单文件后，先跑 `pmagent infra sync-status --workspace <workspace> --json`。
- 有 `pending_files` 且 adapter 可用时，必须先主动询问用户是否同步到飞书 Wiki；用户确认后再跑 `pmagent infra wiki-push --workspace <workspace> --json`。默认使用内置 lark adapter（检测到可用且已配置的 `lark-cli`），自定义空间用 `PMAGENT_FEISHU_WIKI_SPACE_ID`，自定义推送策略才用 `PMAGENT_FEISHU_WIKI_PUSH_COMMAND`；ledger 是成功证据。
- 新 project 的飞书基础设施由 `pmagent infra bootstrap --project <project> --json` 创建或绑定；目标层级是 project 文件在 `<project>/` 下、Cards Base 与 `workspaces/` 在 `<project>` 下平级、workspace 文件在 `<project>/workspaces/<workspace>/` 下。
- 有 `pending_files` 但无可用 lark adapter / custom command 时，状态块标记 `feishu_sync_pending` 并列出文件；不得声称已同步飞书。
- Base 卡片只走 `infra pull-cards --from-base` / `infra review-card` / `infra push-feedback`，不走 Wiki push。

## Hard Workflow Gates

以下规则是运行时边界，违反即行为错误：

1. **audit_gate**：进入 workspace 正式工作前先跑 audit，主行为是 pull Base cards + review pending cards
2. **review_gate**：Candidate Card accept / reject / snooze 需要用户确认
3. **cadence_gate**：legacy local observation cadence 变更需要用户确认
4. **maintenance_gate**：只有 accepted 信号进入 maintenance
5. **observation_boundary_gate**：Observation 不直接改 PRD
6. **summary_sync_gate**：`workspace-summary.md` 与 current-state 必须同步
7. **requirement_authorship_gate**：`Requirement.md` 由外部 Agent 直接编辑，CLI 不写不补丁不同步
8. **debate_boundary_gate**：当 `debate_review.completed_awaiting_review_count > 0` 时，不直接编辑 `prd/**` 或 `Requirement.md`

## Agent Determinism Gates

以下规则保证 agent 行为稳定、可预测：

1. **state_first_gate**：下一轮问题、建议、review 判断前先刷新状态
2. **backlog_visibility_gate**：有待审 Candidate Card 或 legacy unread observation 时必须先 surface
3. **scoring_conservatism_gate**：readiness 评分必须保守，不允许随意浮点夸大
4. **debate_visibility_gate**：当存在 debate failed / pending review / pending launch 时，先 surface 该状态，再继续推进主流程

## Recommended Practices

- 建议在正式工作前 echo 当前 phase、推荐 skill、原因和下一步
- 建议在正式回复中包含状态块
- 状态块默认使用 markdown 表格
- 状态块之后仍需给出有实质内容的主回答
- 对任何带评分对象（如 readiness、candidate review、maintenance readiness、单卡 scores）的回复，必须展示具体分数，不得只做摘要
- 表格变长不能成为压缩主回答深度的理由；先完整展示评分，再继续给出充分解释、判断依据和下一步建议
- 读取顺序可在低风险场景下按需微调，但默认遵循本文件

## Score Visibility Contract

- 只要对话回复中引用了 score-bearing object，就必须渲染原始评分表。
- score-bearing object 包括但不限于：
  - `readiness`
  - 任意包含 `score` / `scores` / `dimensions` / `threshold` / `gates` / `blocking_gates` 的对象
- prose summary 只能补充解释，不能替代表格。
- 不允许隐藏维度分数；如果对象里有 `dimensions`，就必须完整展示。
- 不允许因为表格较长而省略分析深度、风险说明、原因解释或下一步建议。

## Depth Retention Rule

- 表格只负责“让评分可见”，不负责替代分析。
- 正式回复至少要同时包含：
  1. 评分表
  2. 对评分的解释
  3. 风险 / 阻塞项说明
  4. 下一步建议
- 如果评分对象很多，可以拆成多张表或多段输出，但不能把解释压缩成一句话带过。

## State-First Execution Rule

- phase / active_step 推进前先刷新当前状态
- 优先使用阶段专用状态命令：
  - clarifying -> `pmagent clarify status --workspace <workspace> --json`
  - researching -> `pmagent research status --workspace <workspace> --json`
  - delivery -> `pmagent prd status --workspace <workspace> --json`
  - maintaining -> `pmagent observe maintenance-status --workspace <workspace> --json`
  - candidate-review -> `pmagent observe review --workspace <workspace> --json`
- 没有专用状态命令时，退回 `pmagent status --workspace <workspace> --json`
- 在 `pmagent start` / `pmagent resume` / `pmagent next` / `pmagent review` 返回 `debate-failure` / `debate-review` / `debate-launch` 时，优先按提示处理 Debate，而不是继续普通 phase 工作

## Debate Workflow Rule

- Debate 是一个旁路 step，不是 mode，也不切换 clarifying / researching / delivery / maintaining phase
- 当前 Debate 执行协议采用 **markdown-first**：
  - 每轮直接落 `context/debates/<topic>/round-N-{pro,con}.md`
  - 最终落 `context/debates/<topic>/synthesis.md`
  - 固定 heading / section 由 orchestrator + validator 保证；JSON 只作为兼容 fallback，不是主协议
- Debate 是否开启，默认仍由主 Agent 提议、用户确认；不要把“建议开 debate”伪装成自动化硬 gate
- 当前实现已接入的主流程 surface 包括：
  - `pmagent start`
  - `pmagent resume`
  - `pmagent next`
  - `pmagent review`
  - `session_bootstrap`
  - `state_surface`
- Debate 默认执行器配置文件位于 `config/debate-executors.yaml`；`pmagent init` / `workspace-init` 后应默认存在
- 如果 Debate 因执行器或模型不可用而无法启动 / 运行，优先引导用户编辑 `config/debate-executors.yaml`，而不是继续假设默认配置在当前机器可用
- 如果 Debate 已完成待裁决，使用：
  - `pmagent debate review --workspace <workspace> --topic <topic>`
  - `pmagent debate resolve --workspace <workspace> --topic <topic> --accepted|--rejected|--deferred`
- 已 resolved 的 topic 不应再次进入 debate review；如果 topic 失败需重跑，优先使用新的 topic slug，或仅对 failed topic 使用 `pmagent debate start --force`
- 当前未实现的 Debate 增强能力（例如 consumed 闭环、bash review gate、机会提示 hooks）仍属于后续阶段，不要假设它们已经自动生效

## Agent Questioning Rule

- readiness 只负责告诉你当前是否可以推进、当前 gates 和切换建议，不直接规定问题文本
- 不要机械复述模板问题；结合当前状态、历史回答和项目语境提问
- 用户回答后，先通过 CLI 落原始内容，再由外部 Agent 判断评分并回写
- 不要问自己能查到的事实：如果答案可以通过 `pmagent retrieve` / `pmagent search` / 当前 workspace 文件获得，先检索再问
- 每个 phase 在准备结束前，至少做一次 pressure pass，回头挑战当前结论、关键假设或 scope 边界

## Phase-End Pressure Pass Rule

- `clarifying` 结束前，至少做一次回头挑战，优先检查：
  - 当前边界是否只是“顺着描述自然收敛”，而没有被真正压实
  - `non-goals` / `decision boundaries` 是否真的明确
- `researching` 结束前，至少做一次回头挑战，优先检查：
  - 当前证据是否真的支持当前方向
  - 是否只是积累了 research note，而没有形成足够强的判断
- pressure pass 的形式可以是：
  - 追问一个被忽略的 tradeoff
  - 质疑一个最核心的前提
  - 用相反视角重述一次问题
  - 要求补一个最关键的例子 / 证据

## Questioning Boundary

- 提问策略不以“评分维度”作为前台语言
- 不要对用户说“现在在补 scope / intent / outcome”
- 真正面向用户的问题应围绕：
  - 当前最高杠杆的未决问题
  - 关键边界
  - 关键风险
  - 关键 tradeoff
- readiness 维度只属于后台推进控制，不属于前台提问文案

## Clarifying / Research Scoring Rule

用户回答 clarifying 问题或写入 research 记录后：

1. 用户只负责提供自然语言内容
2. 外部 Agent 负责理解内容语义
3. 外部 Agent 负责决定：
   - 哪些维度要更新
   - 每个维度的绝对分值是多少
   - 哪些 gates 被解除
4. 外部 Agent 再调用：
   - `pmagent clarify set-scores --patch-file <file>`
   - `pmagent research set-scores --patch-file <file>`

Rules:

1. 不再使用 `clarify answer --dimension ... --quality ...`
2. 评分更新不由用户手工指定
3. 提问策略不以评分最低项为直接驱动
4. 评分只保留在 `clarifying` 和 `researching`
5. `delivery` / `maintaining` / `candidate-review` 不再保留评分机制

## Observation Policy Rule

- observation 是否开启，以及 cadence 是多少，属于用户策略决策，不应静默假设
- 默认初始化时，如果用户还没做出最终决策，保持 `decision_status = unresolved`
- 如果用户只是暂缓决定（例如“以后再问我”），继续保持 `unresolved`
- 只有用户**明确拒绝** observe，才把状态记为 `manual`
- 至少在两个节点显式询问一次：
  1. `workspace-init/start` 后
  2. 准备进入 PRD 前（如果前面仍未明确）
- candidate-review 一轮结束后，如果系统给出 cadence recommendation，应询问用户是否调整 cadence

## Maintenance Ownership Rule

- `draft-maintenance` 负责生成 maintenance 草稿容器与证据引用
- maintenance 的语义判断（哪些 accepted signal 应该如何改 PRD / Requirement / decisions）由外部 Agent 完成
- `apply-maintenance` 只负责 finalize / changelog / consume cards / 状态收口，不自动改 canonical PRD 正文

## Requirement Lifecycle Rule

- `Requirement.md` 是稳定需求共识正文；**正文维护权属于外部 Agent**
- pmagent CLI **不写、不补丁、不同步** `Requirement.md` 的正文；`workspace-init` 只允许做一次性骨架初始化
- 原始问答与素材继续写入 `context/clarifying-log.md` / `research/research-log.md` / `decisions/`，由 Agent 消化后按需更新 `Requirement.md`
- `workspace-summary.md` 负责当前状态、导航与压缩摘要；`Requirement.md` 负责稳定需求共识，两者不互相替代

## Phase Raw Logging Rule

- 不再维护 workspace 级全局聊天记录文件
- clarifying 阶段的原始聊天/问答历史由 `context/clarifying-log.md` 承接，并应尽量保留该阶段的完整原始内容
- researching 阶段的原始聊天/记录历史由 `research/research-log.md` 承接，并应尽量保留该阶段的完整原始内容
- `Requirement.md` / `workspace-summary.md` / `decisions/` 负责结论、状态与结构化沉淀，不替代 phase raw log

更新时机由 Agent 自行判断，建议：

  - 关键共识变化后（如 scope 收敛、关键 tradeoff 拍板）
  - 进入 research 或起 PRD 前，确认 Requirement 反映了最新共识
  - clarifying 阶段每轮答完，判断是否要把新共识写入

## CLI Surface Rule

Canonical user-facing entrypoints should stay small:

- State/navigation: `status`, `start`, `resume`, `next`, `review`.
- Phase work: `clarify`, `research`, `prd`, `dev`, `observe`.
- Integration work: `infra`.
- Setup/ops: `init`, `upgrade`, `workspace-init`, `switch`, `skills-sync`.

Legacy aliases and generator-style shortcuts are intentionally unsupported. Do
not put removed spellings in docs, generated suggestions, or automation.

`dev-readiness` is a local skill executed by an external Agent, not a CLI generator.
The `pmagent dev` CLI only lists slice artifacts and records execution evidence.

## 核心命令

```bash
pmagent init --dir <data_dir>
pmagent workspace-init --project <project> --workspace <workspace>
pmagent status
pmagent route
pmagent review
pmagent start
pmagent next
pmagent resume
pmagent clarify status
pmagent clarify answer --answer "<answer>"
pmagent clarify set-scores --patch-file <file>
pmagent research start --workspace <workspace> --json
pmagent research status
pmagent research note --summary "<summary>"
pmagent research set-scores --patch-file <file>
pmagent prd status
pmagent prd review
pmagent prd challenge
pmagent prd init-draft
pmagent dev slices --workspace <workspace> --json
pmagent dev run-record --workspace <workspace> --slice <slice-id> --command "<command>" --status passed|failed|blocked
pmagent dev lesson-review --workspace <workspace> --json
pmagent observe audit --workspace <workspace> --run-catch-up --json
pmagent observe review --workspace <workspace>
pmagent observe maintenance-status --workspace <workspace>
pmagent observe run --project <project>  # legacy/local-only
pmagent observe unread --workspace <workspace>
pmagent observe mark-read --workspace <workspace> --ids <observation-id>...
pmagent observe accept|reject|snooze ...
pmagent observe enable --project <project> --cadence daily --confirm-cadence  # legacy/local-only
pmagent observe set-cadence --project <project> --cadence weekly --confirm-cadence  # legacy/local-only
pmagent observe disable --project <project>
pmagent observe draft-maintenance --workspace <workspace>
pmagent observe apply-maintenance --workspace <workspace>
pmagent infra protocol --workspace <workspace>
pmagent infra sync-status --workspace <workspace> --json
pmagent infra wiki-push --workspace <workspace> --json
pmagent infra pull-cards --from-base --workspace <workspace> --json
pmagent infra pull-cards --from <cards.json> --workspace <workspace>
pmagent infra review-card --workspace <workspace> --card <card-id> --status accepted|rejected|snoozed
cat config/debate-executors.yaml
pmagent debate start --workspace <workspace> --thesis "<thesis>" --axis "<axis>"
pmagent debate status --workspace <workspace> [--topic <topic>]
pmagent debate show --workspace <workspace> --topic <topic> [--round <n> | --synthesis]
pmagent debate review --workspace <workspace> --topic <topic>
pmagent debate resolve --workspace <workspace> --topic <topic> --accepted|--rejected|--deferred
pmagent workspace-close --workspace <workspace>
pmagent export --project <project> --workspace <workspace>
```

## 对话状态块模板

```md
状态概览

| 字段 | 值 |
| --- | --- |
| 当前 phase | `<phase>` |
| 当前工作面 | `<guided-view>` |

Readiness 概览

| 字段 | 值 |
| --- | --- |
| readiness phase | `<phase>` |
| 总分 | `<score>` |
| blocking gates | `<blocking-gates>` |

Readiness 评分表

| 评分项 | 分数 |
| --- | --- |
| overall | `<score>` |
| `<dimension-a>` | `<value-a>` |

下一步

| 字段 | 值 |
| --- | --- |
| 动作 | `<next-step-id>` |
| 原因 | `<next-step-reason>` |
```

## 用户覆盖区

在这里添加项目特定的 agent 行为覆盖。

<!-- PMAGENT:MANAGED:END -->
