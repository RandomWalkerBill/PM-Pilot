# PMAgent 当前方案说明：飞书文件层、分析 Agent 与研发纵向拆分

日期：2026-04-30

## 1. 一句话方案

PMAgent 当前方案不是“自建完整服务器优先”，也不是“飞书完全替代服务器”，而是：

```text
本地主流程保留 canonical 文件和 PM 工作流协议；
飞书作为文件协作层，承载所有主流程文件、dev 文件、分析任务、建议和反馈；
第一版分析 Agent 读取飞书上的全部文件来评估主流程和 dev 的过程问题；
研发侧通过 vertical slice 协议接入 GitHub 代码仓库；
代码层仍由 GitHub 管理，研发经验由研发侧 Agent 产生候选沉淀，再由 PMAgent 结构化 review 和晋升。
```

核心目标是用更轻的第一版验证三件事：

1. PM 流程能否通过文件协议稳定驱动外部 Agent；
2. 飞书能否作为团队可见的文件协作层；
3. 研发过程能否通过 slice、run evidence、lesson review 逐步积累经验。

## 2. 总体架构

```text
外部 Agent / 用户
  Codex / Claude Code / Kiro
        |
        v
本地主流程 Mainflow
  Requirement.md
  prd/current.md
  decisions/
  research/
  dev/dev-plan.md
  dev/slices/*.md
  .pmagent/current-state.json
  .pmagent/sync/outbox
  inbox/
        |
        | sync push / pull
        v
飞书文件协作层 Feishu File Layer
  Docs / Wiki:
    Requirement / PRD / decisions / research / dev-plan / slices / runs / QA / lessons
  Index tables:
    最小机器索引，不是看板层
    Workspaces / Artifacts / SyncEvents
    AnalysisRuns / Suggestions / Feedback
    Slices / DevRuns / TestRuns / Lessons
  IM:
    通知、建议卡片、人工决策提醒
        |
        | read all Feishu files / analyze / write suggestions
        v
飞书 claw / 分析 Agent
  读取飞书文件层中的主流程和 dev 全部文件
  生成 PM / dev / 跨层过程 suggestion
  写回飞书 Suggestions
        |
        | pull suggestions / feedback
        v
本地主流程 inbox
  用户 accept / ignore / defer
  需要时回到 clarify / research / PRD / dev-readiness


研发侧 Dev
  GitHub repo / worktree / branch / tests / PR
        ^
        |
  研发侧 Agent 执行 slice，产出 run evidence / lesson candidates
        ^
        |
  PMAgent slice contract + lesson review + accepted lessons
```

## 3. 各层职责

### 3.1 本地主流程

本地主流程是 PMAgent 的协议内核，负责：

- 保存 canonical artifact；
- 维护 `current-state.json`；
- 维护 sync outbox；
- 生成和处理 inbox；
- 管理 skill registry、recommended skills、readiness；
- 生成 dev-plan 和 vertical slices；
- 从飞书拉取 suggestion 和 feedback；
- 把远端变化转成本地可审查的 inbox item。

本地主流程不负责：

- 直接作为 Agent runtime；
- 接管代码仓库；
- 让远端直接覆盖本地 PRD；
- 自动采纳分析 Agent 建议；
- 自动把经验写成永久规则。

关键原则：

```text
local canonical wins
remote is mirror/advisory
```

### 3.2 飞书文件协作层

飞书承担第一版的远端文件协作层，负责：

- 用 Docs / Wiki 保存所有主流程文件和 dev 文件；
- 用最小索引表保存 workspace、artifact、sync event、suggestion、feedback、slice、run、lesson 的机器可读元数据；
- 用 IM 推送同步结果、分析建议、风险和人工决策提醒；
- 保存分析任务和输出；
- 保存用户对 suggestion 的 accept / ignore / defer。

飞书不作为：

- 本地文件的权威源；
- Git 仓库；
- 冲突裁判；
- 无限制 API 通道；
- PMAgent 同步协议本身；
- 服务器侧看板层。

### 3.3 飞书 claw / 分析 Agent

第一版分析 Agent 完全交给飞书 claw 做。

分析 Agent 的职责：

- 读取飞书 Docs / Wiki 中的 Requirement、PRD、research、decisions、dev-plan、slices、runs、QA、lessons；
- 读取最小索引表中的 workspace / artifact / slice / run / feedback 信息；
- 分析需求缺口、PRD 风险、验收标准、slice 粒度、测试策略、run evidence 和 lesson 质量；
- 把文件问题映射回主流程或 dev 的具体环节，例如 requirement / research / decision / PRD / dev-readiness / slice / QA / lessons；
- 生成 suggestion，建议是否需要 clarify、research、debate、observation、PRD 回炉、dev-plan 修订、slice 拆分或补充测试证据；
- 对研发侧 Agent 已产出的 lesson candidate 做远端复盘、去重、聚类和补充建议；
- 写回飞书 `Suggestions`，必要时写入二次整理后的 `LessonReviewSuggestions`。

分析 Agent 不应该：

- 直接修改本地 canonical 文件；
- 直接改 PRD / Requirement；
- 直接执行 research / debate / dev；
- 直接把 suggestion 标记为 accepted；
- 取代研发侧 Agent 做一手研发经验沉淀；
- 绕过 PMAgent inbox。

### 3.4 服务器层

当前第一版可以不急着做完整服务器。

服务器和看板层在 V1 中可以缺席。若保留很薄的一层，也只做基础设施：

- 定时触发分析 Agent；
- 错误告警。

服务器后续再承担：

- 更稳定的 job queue；
- API rate limit 队列；
- 分析任务审计；
- 权限隔离；
- 替换或补充飞书 claw 的自建 analyzer。

也就是说：

```text
V1: Feishu file layer + 分析 Agent 先跑闭环
V2: server 回来做稳定性、调度、审计和企业化能力
```

### 3.5 研发侧

研发侧使用真实代码仓库，不复制代码，不让飞书成为代码存储。

代码管理仍由 GitHub 承担：

- GitHub repository；
- branch；
- worktree；
- commit；
- PR；
- CI；
- 测试命令；
- repo 内 AGENTS.md。

PMAgent 只加研发协议层：

- codebase registry；
- dev-plan；
- vertical slice；
- slice run；
- test evidence；
- dev feedback；
- lesson candidates；
- accepted lessons。

研发侧 Agent 是研发经验的一手沉淀者。原因是它直接经历：

- 读代码和定位模块；
- 选择实现路径；
- 修改文件；
- 处理构建和测试失败；
- 解决 repo 约束、hooks、AGENTS.md 要求；
- 记录哪些判断后来被验证或推翻。

这些信息只有研发执行现场最完整。分析 Agent 可以读飞书上的 run evidence 做二次分析，但不应替代研发侧 Agent 生成第一手候选经验。

## 4. 飞书最小索引表模型

这些表不是看板层，只是文件层背后的机器索引、同步账本和分析输入。

### 4.1 Workspaces

| 字段 | 说明 |
|---|---|
| `workspace_id` | PMAgent workspace id |
| `project_id` | 所属项目 |
| `phase` | clarifying / researching / prd / dev / maintenance |
| `readiness_score` | 当前 readiness |
| `active_skill` | 当前工作面 |
| `pending_inbox_count` | 待处理 inbox 数 |
| `last_push_at` | 最近本地同步时间 |
| `last_analysis_at` | 最近分析时间 |

### 4.2 Artifacts

| 字段 | 说明 |
|---|---|
| `artifact_id` | artifact id |
| `workspace_id` | workspace |
| `kind` | requirement / prd / decision / research / dev-plan / slice |
| `local_path` | 本地路径 |
| `sha256` | 本地文件 hash |
| `base_revision` | 本地基准 revision |
| `feishu_doc_url` | 飞书镜像文档 |
| `updated_at` | 更新时间 |

### 4.3 SyncEvents

| 字段 | 说明 |
|---|---|
| `event_id` | PMAgent sync event id |
| `workspace_id` | workspace |
| `kind` | file_changed / state_changed / feedback_sent |
| `local_path` | 相关路径 |
| `sha256` | 内容 hash |
| `base_revision` | 基准 revision |
| `status` | pending / acked / failed / conflict |
| `error` | 错误信息 |
| `created_at` | 创建时间 |

### 4.4 AnalysisRuns

`AnalysisRuns` 是第一版分析 Agent 的任务协议，必须有。

| 字段 | 说明 |
|---|---|
| `run_id` | 分析任务 id |
| `workspace_id` | workspace |
| `trigger` | manual / scheduled / push |
| `input_hash` | 输入快照 hash |
| `status` | pending / running / completed / failed |
| `policy_version` | 分析策略版本 |
| `claw_session_id` | claw 会话或执行 id |
| `started_at` | 开始时间 |
| `completed_at` | 完成时间 |
| `error` | 错误信息 |

没有 `AnalysisRuns`，就无法判断分析 Agent 到底分析了哪个版本、是否重复、是否失败、失败后能否重跑。

### 4.5 Suggestions

| 字段 | 说明 |
|---|---|
| `suggestion_id` | suggestion id |
| `run_id` | 来源分析任务 |
| `workspace_id` | workspace |
| `kind` | research / debate / observation / prd / dev / process |
| `title` | 标题 |
| `reason` | 建议理由 |
| `evidence_path` | 证据对应本地路径 |
| `evidence_sha256` | 证据文件 hash |
| `recommended_skill` | 推荐 skill |
| `status` | pending / accepted / ignored / deferred |
| `created_at` | 创建时间 |

### 4.6 Feedback

| 字段 | 说明 |
|---|---|
| `feedback_id` | feedback id |
| `suggestion_id` | suggestion |
| `workspace_id` | workspace |
| `signal` | explicit_user_accept / ignore / defer |
| `actor` | 操作者 |
| `created_at` | 创建时间 |

### 4.7 Slices

| 字段 | 说明 |
|---|---|
| `slice_id` | vertical slice id |
| `workspace_id` | workspace |
| `codebase_id` | 绑定代码库 |
| `title` | 标题 |
| `status` | planned / ready / running / blocked / done |
| `base_commit` | 起点 commit |
| `branch` | 开发分支 |
| `worktree_path` | worktree 路径 |
| `owned_paths` | 主要负责文件 |
| `shared_paths` | 共享风险文件 |
| `test_commands` | 验证命令 |

### 4.8 DevRuns / TestRuns

| 表 | 作用 |
|---|---|
| `DevRuns` | 记录每次 slice 执行，包含 run id、agent、branch、changed files、status |
| `TestRuns` | 记录测试命令、退出码、摘要、日志链接 |

### 4.9 Lessons

| 表 | 作用 |
|---|---|
| `LessonCandidates` | 研发侧 Agent 从 slice 执行过程中提取的候选经验 |
| `AcceptedLessons` | review 后正式进入经验库的经验 |
| `RejectedLessons` | 被拒绝的经验，防止重复提出 |
| `LessonReviewSuggestions` | 分析 Agent 对候选经验做去重、聚类、补证据、跨项目复盘后给出的二次建议 |

## 5. 主流程同步闭环

### 5.1 Push

本地主流程发生文件或状态变化：

```text
Requirement.md / PRD / decisions / research / dev-plan / slices / current-state
```

PMAgent 生成 sync event：

```json
{
  "event_id": "evt-...",
  "workspace": "demo",
  "kind": "file_changed",
  "path": "workspaces/demo/prd/current.md",
  "sha256": "...",
  "base_revision": "rev-123",
  "created_at": "..."
}
```

然后写入飞书：

- `SyncEvents`；
- `Artifacts`；
- Docs / Wiki 镜像；
- `Workspaces` 摘要；
- 必要时 IM 通知。

### 5.2 Pull

PMAgent 从飞书拉取：

- pending suggestions；
- sync conflicts；
- feedback status；
- lesson candidates；
- dev feedback。

拉回后不直接改 canonical 文件，而是生成 inbox item：

```text
inbox/pending/item-*.json
```

用户或外部 Agent 通过 `review-inbox` 处理。

### 5.3 Feedback

用户在本地接受、忽略或暂缓 suggestion：

```text
accept / ignore / defer
```

PMAgent 写回飞书 `Feedback` 表，并更新 `Suggestions.status`。

## 6. 分析 Agent 闭环

第一版分析流程：

```text
1. PMAgent push 最新 workspace 状态到飞书
2. 创建或更新 AnalysisRuns 记录
3. 分析 Agent 读取飞书 Docs / Wiki 中的全部主流程和 dev 文件
4. 分析 Agent 结合最小索引表判断输入版本、artifact 状态和历史反馈
5. 分析 Agent 生成 Suggestions，必要时对 LessonCandidates 生成二次复盘建议
6. Suggestions 写回飞书
7. PMAgent pull 到本地 inbox
8. 用户 review
9. feedback 写回飞书
```

分析 Agent 输出必须结构化，不能只写自然语言总结。

建议输出约束：

```json
{
  "schema_version": 1,
  "suggestions": [
    {
      "scope": "mainflow",
      "kind": "prd",
      "title": "补充验收标准",
      "reason": "当前 PRD 只描述实现方向，缺少用户可观察行为。",
      "evidence": [
        {
          "path": "workspaces/demo/prd/current.md",
          "sha256": "...",
          "summary": "第 4 节未定义失败态。"
        }
      ],
      "mapped_to": {
        "flow_area": "prd",
        "artifact": "prd/current.md"
      },
      "recommended_action": "challenge_prd"
    }
  ],
  "lesson_review_suggestions": []
}
```

建议必须能映射回流程位置：

| 问题 | 映射位置 | 推荐动作 |
|---|---|---|
| 需求目标含糊 | Requirement | clarify |
| 事实判断缺证据 | Research | research |
| 关键取舍未拍板 | Decisions | debate / write decision |
| 外部信号持续变化 | Observation | observation |
| PRD 验收标准不可测 | PRD | challenge-prd / rewrite PRD |
| PRD 与 dev-plan 不一致 | Dev Readiness | update dev-plan |
| slice 太大或不垂直 | Slice | split slice |
| run evidence 缺失 | Dev Run | rerun / add evidence |
| QA 失败暴露产品口径缺失 | PRD / QA | product decision |
| lesson candidate 证据不足 | Lessons | defer / request evidence |

## 7. 研发 vertical slice 闭环

### 7.1 从 PRD 到 dev-plan

当 PRD 基本稳定后，用户或外部 Agent 运行 dev-readiness 工作面：

```text
PRD
  -> dev-readiness
  -> dev/dev-plan.md
  -> dev/slices/SL-001.md
  -> dev/slices/SL-002.md
```

dev-plan 负责说明：

- 产品目标；
- 实现边界；
- 测试策略；
- 领域语言；
- 模块风险；
- slice 拆分顺序；
- ready for dev checklist。

### 7.2 Slice 契约

每个 slice 是一个可交付、可验证、尽量端到端的增量。

`dev/slices/SL-001.md` 至少包含：

```text
# Slice SL-001: <标题>

## Goal

## User Story

## What to Build

## Acceptance Criteria

## Public Behavior Tests

## Codebase

## Owned Paths

## Shared Paths

## Commands

## Out of Scope
```

### 7.3 代码库登记

PMAgent 不复制代码库，而是登记代码库：

```json
{
  "codebases": [
    {
      "id": "pmagent",
      "github_url": "https://github.com/<org>/<repo>",
      "local_root": "C:/Users/20663/Desktop/pmagent/pmagent",
      "vcs": "git",
      "base_branch": "main",
      "test_commands": ["pytest"],
      "current_commit": "..."
    }
  ]
}
```

### 7.4 Worktree per slice

并行研发时推荐：

```text
一个 slice 一个 git worktree
一个 slice 一个 branch
```

示例：

```text
pmagent/                 # main checkout
pmagent-sl-001/          # slice SL-001 worktree
pmagent-sl-002/          # slice SL-002 worktree
```

slice 元数据：

```json
{
  "slice_id": "SL-001",
  "codebase_id": "pmagent",
  "base_commit": "...",
  "branch": "pmagent/sl-001-dev-readiness",
  "worktree_path": "../pmagent-sl-001",
  "owned_paths": [
    "src/pmagent/dev_readiness.py",
    "tests/test_dev_readiness.py"
  ],
  "shared_paths": [
    "src/pmagent/cli.py"
  ]
}
```

规则：

- `owned_paths` 是 slice 主要修改范围；
- `shared_paths` 必须显式声明；
- 未声明的共享文件不能随便改；
- 跨 slice 冲突进入 inbox；
- 合并通过 Git / PR / review 完成。

## 8. 代码管理原则

代码权威源：

```text
GitHub repository
```

PMAgent 记录：

- slice 对应 branch；
- base commit；
- GitHub repository URL；
- touched files；
- test commands；
- test result；
- decision；
- blocker；
- dev feedback；
- lesson candidate。

PMAgent 不做：

- 替代 Git；
- 存储代码全文作为权威副本；
- 自动合并冲突；
- 绕过 repo AGENTS.md；
- 绕过测试和 review。

## 9. 研发经验沉淀

### 9.1 不靠聊天记忆

系统变聪明不能依赖“模型记得聊过什么”，而要依赖结构化证据。

研发经验的一手沉淀应该由研发侧 Agent 完成，而不是分析 Agent。研发侧 Agent 在 slice 执行现场掌握最完整的代码上下文、失败过程、测试证据、实现取舍和 repo 约束；分析 Agent 只能看到同步后的飞书文件层记录，更适合做二次复盘和跨项目整理。

每次 slice 执行生成 run 记录：

```text
dev/runs/SL-001/run-20260430-001/
  run.json
  touched-files.json
  commands.jsonl
  test-results.json
  decisions.md
  blockers.md
  diff-summary.md
  lessons-candidates.jsonl
```

### 9.2 候选经验

研发侧 Agent 在 slice 收尾时必须从 run evidence 中提取候选经验：

```json
{
  "kind": "test_gotcha",
  "title": "current-state v1 workspace must auto-upgrade before dev snapshot",
  "evidence": "tests/test_init_upgrade.py failed before migration helper",
  "confidence": "medium",
  "applies_to": ["current_state", "schema_migration"]
}
```

但这只是候选经验。

候选经验应尽量绑定证据，而不是泛泛总结。至少要关联：

- slice id；
- run id；
- touched files；
- 失败或成功的测试命令；
- 相关决策；
- 适用模块或模式；
- 置信度。

分析 Agent 可以读取这些候选经验，做以下二次工作：

- 去重；
- 合并相似经验；
- 找出缺少证据的经验；
- 发现跨 workspace / 跨项目重复出现的模式；
- 生成 `LessonReviewSuggestions`，提醒哪些候选经验值得晋升或应该拒绝。

但分析 Agent 的二次建议仍然不能直接晋升为永久经验。

### 9.3 Review 后晋升

经验进入系统要经过 inbox：

```text
lesson_candidate
  -> inbox
  -> accept / ignore / defer
  -> accepted_lessons / rejected_lessons
```

被接受后才用于后续推荐和分析。

### 9.4 下一次如何使用经验

下一次生成 slice 或执行研发前，PMAgent 检索：

- 相似历史 slice；
- 相关模块；
- 相关失败测试；
- accepted lessons；
- rejected lessons；
- 当前 PRD / dev-plan。

然后形成提示：

```text
这个 slice 会触碰 current_state.py。
历史上 schema migration 容易漏旧 workspace 兼容。
建议先补 tests/test_init_upgrade.py，再改实现。
```

这就是“越用越聪明”的具体机制。

## 10. 关键不变量

第一版必须守住这些不变量：

1. 本地 canonical 文件优先；
2. 飞书是 mirror/advisory，不是本地文件权威源；
3. 分析 Agent 只生成 suggestion 和 lesson review suggestion；
4. 研发侧 Agent 生成一手 lesson candidate；
5. 分析 Agent 只能对 lesson candidate 做二次复盘和建议，不能直接晋升经验；
6. 远端变化必须进 inbox，不自动改本地；
7. suggestion 必须有 evidence；
8. lesson candidate 必须 review 后才能晋升；
9. 代码由 GitHub 管理；
10. slice 必须绑定 base commit、branch、owned paths、test commands；
11. 失败、冲突、限频都要结构化记录；
12. 后续服务器可以替换或补充分析 Agent，但不能破坏协议。

## 11. 风险与缓解

| 风险 | 说明 | 缓解 |
|---|---|---|
| 飞书 API 限频 | 表格、Docs、下载、导出都有 OpenAPI 限流 | 本地/远端都做 rate limit、cache、retry、backoff |
| 数据双主写入 | 人在飞书改文档，本地也改文件 | 飞书文档默认镜像；远端变化进 inbox，不自动覆盖 |
| 分析 Agent 输出不稳定 | 自然语言建议可能缺字段、证据不准 | 强制 JSON schema / 索引字段校验；研发经验一手沉淀不交给分析 Agent |
| 无法追踪分析任务 | 不知道分析 Agent 分析了哪个版本 | 必须有 `AnalysisRuns` 和 `input_hash` |
| 经验污染 | 错误经验被自动固化 | lesson candidate 必须 review 后晋升 |
| 代码冲突 | 多个 slice 同时改共享文件 | worktree per slice、owned/shared paths、冲突进 inbox |
| 权限复杂 | user/bot/claw/server 权限不一致 | 明确身份模型，最小权限，错误写入 diagnostics |

## 12. MVP 落地顺序

### Step 1：本地协议先行

- `current-state.json` 保留；
- `sync outbox` 保留；
- `inbox` 统一；
- artifact 带 `sha256` / `base_revision`；
- slice 文件模板落地。

### Step 2：飞书文件层

- 建最小索引表；
- push Workspaces / Artifacts / SyncEvents；
- 创建 Docs / Wiki 文件树并同步主流程和 dev 文件；
- IM 通知可选。

### Step 3：分析 Agent 诊断

- 建 `AnalysisRuns`；
- 分析 Agent 读取飞书全部文件；
- 分析 Agent 写 `Suggestions`，并映射到主流程或 dev 的具体位置；
- PMAgent pull 成本地 inbox。

### Step 4：feedback 闭环

- 本地 accept / ignore / defer；
- 写回飞书 `Feedback`；
- 更新 `Suggestions.status`。

### Step 5：研发 slice

- codebase registry；
- dev-plan；
- slice contract；
- branch/worktree 绑定；
- run evidence；
- test evidence；
- 研发侧 Agent 生成 lesson candidates。

### Step 6：经验沉淀

- lesson candidates 进入 inbox；
- 分析 Agent 可做二次去重、聚类和复盘建议；
- inbox review；
- accepted lessons；
- 后续 slice 生成时检索经验。

### Step 7：后续基础设施增强

- 分析任务调度；
- rate limit 队列；
- 后续自建 analyzer。

## 13. 当前方案的产品表述

推荐对外表述：

```text
PMAgent 是本地优先的 PM-to-dev 工作流协议层。
第一版使用飞书作为文件协作层，使用飞书 claw / 分析 Agent 作为外部诊断后端。
本地文件和 GitHub 仓库仍是权威源。
飞书负责保存团队可见的主流程文件、dev 文件、建议卡片和反馈。
研发侧 Agent 通过 vertical slice、run evidence 和 lesson candidates 沉淀一手经验，PMAgent 通过 lesson review 将其晋升为可复用经验。
```

不推荐表述：

```text
飞书替代 PMAgent server。
PMAgent 接管代码仓库。
分析 Agent 自动优化 PMAgent。
分析建议会自动改 PRD。
```

## 14. 最终判断

当前方案是可行的，而且适合作为第一版。

它的优势是：

- 不需要第一版就自建完整服务器；
- 可以快速利用飞书的文档、评论、权限、IM 和最小索引能力；
- 分析 Agent 先交给 claw，降低实现成本；
- 本地 canonical 和 GitHub 权威源仍然保留；
- 后续可以自然演进到自建 server analyzer；
- 研发经验可以通过结构化证据沉淀，而不是依赖聊天记忆。

但必须守住底线：

```text
飞书和分析 Agent 是第一版文件协作与诊断后端，不是 PMAgent 协议内核。
```

只要这个边界不丢，方案可以稳定推进。
