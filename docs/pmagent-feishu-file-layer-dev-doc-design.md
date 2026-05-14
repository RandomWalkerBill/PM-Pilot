# PMAgent 飞书文件层优先设计：文件体系、研发文档与同步边界

日期：2026-04-30

## 1. 背景判断

当前明确暂不做服务器侧看板层。

更合理的 V1 目标是：

```text
先把 PMAgent 的文件体系稳定落到飞书文件层；
让飞书承载团队可见、可评论、可归档的项目文件；
本地工作区继续承担 Agent 可执行的工作副本、状态协议和同步账本；
所有文件层内容，包括主流程文件和 dev 文件，都同时保存在本地并同步到飞书；
代码层全部在 GitHub，PMAgent 只保存代码库链接、分支、提交和运行证据；
分析 Agent 读取飞书上的全部 PM / dev 文件，持续评估流程问题并生成建议。
```

也就是说，第一版重点不是自建服务器看板，而是先做一个可靠的文件协作层：

```text
PMAgent local workspace  <->  Feishu File Layer
```

飞书表格不作为看板层存在，只作为机器可读的文件索引、同步账本和建议记录。

## 2. 核心原则

### 2.1 飞书是长期协作文件层，本地是 Agent 工作副本

推荐采用“双文件形态，单写入入口”的模型：

```text
飞书 Docs / Wiki
  团队长期可见的文件库
  适合阅读、评论、归档、权限、跨团队协作

PMAgent 本地 workspace
  Agent 可读写的工作副本
  适合 diff、hash、测试、hook、命令行执行、无网恢复
```

这里不是“双主写入”。V1 必须避免飞书文档和本地 markdown 同时自由编辑。

推荐约束是：

```text
PMAgent 写本地工作副本，然后发布到飞书。
飞书侧默认用于阅读、评论、建议和人工确认。
飞书正文被人工修改时，不自动覆盖本地，而是生成 inbox / conflict。
```

如果未来要支持“飞书正文反向写回本地”，也要走显式导入和冲突审查，而不是静默覆盖。

### 2.2 暂不做看板层，表格只做机器索引

飞书表格在 V1 的定位是 metadata index 和 sync ledger，不是 Dashboard，也不是用户主要入口。

表格只服务机器读写和少量人工排错，回答这些问题：

- 哪些 workspace 存在；
- 每个 artifact 在飞书哪里；
- 当前 artifact 的 hash / revision / 更新时间是什么；
- 哪些 suggestion / feedback / dev slice 待处理；
- 哪些同步或分析任务失败。

不要第一版追求完整服务器侧看板、拖拽任务流、复杂筛选页面或自建 dashboard。团队主要看飞书 Wiki / Docs 文件树；表格只是文件树背后的索引。

### 2.3 代码不进飞书文件层

飞书文件层保存 PM 和研发协作文档，不保存代码权威副本。

代码权威源仍然是 GitHub：

```text
GitHub repository + branch + commit + PR + CI
```

飞书和 PMAgent 只记录：

- codebase registry；
- GitHub repository URL；
- slice 对应 branch / base commit；
- touched files 摘要；
- test commands 和结果；
- blockers；
- decision；
- lesson candidates。

不要把源码全文同步到飞书作为长期文件层。

## 3. 推荐总体结构

```text
用户 / 外部 Agent
  Codex / Claude Code / Kiro
        |
        v
PMAgent local workspace
  Requirement.md
  workspace-summary.md
  research/
  strategy/
  decisions/
  prd/
  dev/
  exports/
  .pmagent/current-state.json
  .pmagent/sync/
  inbox/
        |
        | publish / pull feedback / detect conflicts
        v
飞书文件层
  Wiki / Docs:
    项目文件、需求文件、PRD、决策、研发计划、slice、run evidence、测试报告、经验复盘
  Index tables:
    机器索引，不是看板
    Workspaces / Artifacts / SyncEvents / Suggestions / Feedback
    Codebases / Slices / DevRuns / TestRuns / Lessons
  IM:
    同步失败、人工决策、suggestion、blocked 提醒
        |
        | read all Feishu files, write structured suggestions
        v
飞书 claw / 分析 Agent
```

服务器侧如果存在，V1 只做薄能力：

- 定时或手动触发同步；
- 调用飞书 API；
- 记录失败诊断；
- 后续再承接 job queue、权限隔离和分析审计。

## 4. 飞书文件层目录设计

建议在飞书 Wiki 下建立一个 PMAgent 根空间。

```text
PMAgent/
  00-Index/
    Workspace Index
    Artifact Index
    Dev Index
  Projects/
    <project>/
      00-Project Home
      01-Project Memory
      02-Strategy
      Workspaces/
        <workspace>/
          00-Workspace Summary
          01-Requirement
          02-Research
          03-Decisions
          04-PRD
            current
            versions/
          05-Dev
            dev-plan
            slices/
              SL-001
              SL-002
            runs/
              SL-001-run-20260430-001
            qa/
            lessons/
          06-Exports
```

命名规则：

- project 使用 PMAgent `project_id`；
- workspace 使用 PMAgent `workspace_id`；
- 每个飞书文档标题保留稳定前缀，例如 `PRD - <workspace>`、`SL-001 - <slice title>`；
- 文档正文顶部放一段机器可解析的 metadata。

示例：

```markdown
<!-- pmagent
artifact_id: art_prd_current_demo
workspace_id: demo
kind: prd
local_path: workspaces/demo/prd/current.md
local_sha256: ...
base_revision: rev-...
publish_version: 3
source: pmagent
-->
```

metadata 的目的不是给人看，而是让同步器判断这份飞书文档对应哪个本地 artifact。

## 5. 本地文件体系如何对应飞书

当前运行时数据目录已经有这些核心位置：

```text
<data_dir>/
  config/
  projects/
  workspaces/
  memory/
  skills/
  templates/
  ops/
```

典型 workspace 目前是：

```text
workspaces/<workspace>/
  Requirement.md
  workspace-summary.md
  .pmagent/current-state.json
  context/
  research/
  strategy/
  decisions/
  prd/
  candidate-updates/
  maintenance/
  exports/
```

建议新增研发侧目录，但不要打散现有结构：

```text
workspaces/<workspace>/
  dev/
    dev-plan.md
    codebases.json
    slices/
      SL-001.md
      SL-002.md
    runs/
      SL-001/
        run-20260430-001/
          run.json
          touched-files.json
          commands.jsonl
          test-results.json
          decisions.md
          blockers.md
          diff-summary.md
          lesson-candidates.jsonl
    qa/
      YYYY-MM-DD-<feature>-test-report.md
    lessons/
      accepted-lessons.md
      rejected-lessons.md
```

这样 `dev/` 和 `research/`、`decisions/`、`prd/` 是同级目录，含义清晰：

- `prd/`：产品意图和验收口径；
- `dev/`：把 PRD 转成工程可执行契约；
- `exports/`：面向一次交付或外部消费的打包产物；
- `memory/`：跨 workspace 晋升后的长期经验。

## 6. Artifact 映射表

| 本地路径 | 飞书位置 | 索引表 | 说明 |
|---|---|---|---|
| `workspace-summary.md` | `00-Workspace Summary` | `Artifacts` | 人和 Agent 的压缩入口 |
| `Requirement.md` | `01-Requirement` | `Artifacts` | 需求主文件 |
| `strategy/*.md` | `02-Strategy` 或项目 Strategy 区 | `Artifacts` | 方向和取舍 |
| `research/*.md` | `02-Research` | `Artifacts` | 调研摘要和证据 |
| `decisions/*.md` | `03-Decisions` | `Artifacts` | ADR / 决策记录 |
| `prd/current.md` | `04-PRD/current` | `Artifacts` | 当前 PRD |
| `prd/YYYY-*.md` | `04-PRD/versions` | `Artifacts` | PRD 历史版本 |
| `dev/dev-plan.md` | `05-Dev/dev-plan` | `Artifacts` | 研发计划 |
| `dev/codebases.json` | `05-Dev/codebases` | `Codebases` | 代码库登记 |
| `dev/slices/*.md` | `05-Dev/slices/*` | `Slices` + `Artifacts` | slice 契约 |
| `dev/runs/**/diff-summary.md` | `05-Dev/runs/*` | `DevRuns` | 执行摘要 |
| `dev/runs/**/test-results.json` | `05-Dev/runs/*` | `TestRuns` | 测试结果 |
| `dev/runs/**/lesson-candidates.jsonl` | `05-Dev/lessons` | `LessonCandidates` | 候选经验 |
| `dev/qa/*.md` | `05-Dev/qa` | `TestRuns` + `Artifacts` | QA / 验收报告 |
| `exports/**` | `06-Exports` | `Artifacts` | 对外交付包 |

注意：大体量日志不要直接塞进飞书文档正文。飞书保留摘要、hash、命令、结论和必要附件链接；完整日志可以留本地、CI 或对象存储。

## 7. 最小索引表设计

### 7.1 Workspaces

| 字段 | 说明 |
|---|---|
| `workspace_id` | PMAgent workspace id |
| `project_id` | 所属项目 |
| `phase` | clarify / research / prd / dev / maintenance |
| `summary_doc` | 飞书 workspace summary 链接 |
| `current_prd_doc` | 当前 PRD 链接 |
| `dev_plan_doc` | dev-plan 链接 |
| `last_publish_at` | 最近发布时间 |
| `pending_inbox_count` | 待处理项数量 |
| `last_error` | 最近同步或分析错误 |

### 7.2 Artifacts

| 字段 | 说明 |
|---|---|
| `artifact_id` | 稳定 artifact id |
| `workspace_id` | 所属 workspace |
| `kind` | requirement / prd / decision / research / dev-plan / slice / run / qa |
| `local_path` | 本地路径 |
| `feishu_url` | 飞书文档链接 |
| `feishu_node_token` | 飞书节点 id |
| `local_sha256` | 本地内容 hash |
| `feishu_revision` | 飞书修订标识 |
| `publish_version` | PMAgent 发布版本 |
| `sync_state` | clean / pending / failed / conflict |
| `updated_at` | 更新时间 |

### 7.3 SyncEvents

| 字段 | 说明 |
|---|---|
| `event_id` | 同步事件 id |
| `artifact_id` | 对应 artifact |
| `action` | create_doc / update_doc / update_base / pull_feedback |
| `local_sha256` | 事件发生时的本地 hash |
| `feishu_revision_before` | 更新前飞书 revision |
| `feishu_revision_after` | 更新后飞书 revision |
| `status` | pending / acked / failed / conflict |
| `error` | 错误信息 |
| `created_at` | 创建时间 |

### 7.4 Suggestions / Feedback

| 表 | 作用 |
|---|---|
| `Suggestions` | 分析 Agent 写入建议，必须带 evidence |
| `Feedback` | 用户 accept / ignore / defer 后写回 |

`Suggestions` 至少需要：

```text
suggestion_id
workspace_id
kind
title
reason
evidence_path
evidence_sha256
recommended_action
status
policy_version
```

### 7.5 Codebases / Slices / DevRuns / TestRuns / Lessons

这些表是研发侧接入的最小元数据：

| 表 | 作用 |
|---|---|
| `Codebases` | 记录真实代码库，不保存代码全文 |
| `Slices` | 每个 vertical slice 的契约和状态 |
| `DevRuns` | 每次研发执行的摘要、分支、改动文件 |
| `TestRuns` | 测试命令、退出码、摘要和日志链接 |
| `LessonCandidates` | 研发侧 Agent 提出的候选经验 |
| `AcceptedLessons` | review 后晋升的经验 |
| `RejectedLessons` | 被拒绝的经验，防止重复提出 |

## 8. 同步机制设计

### 8.1 本地 artifact registry

本地需要维护一个 artifact registry，例如：

```text
workspaces/<workspace>/.pmagent/sync/artifacts.json
```

示例：

```json
{
  "schema_version": 1,
  "artifacts": [
    {
      "artifact_id": "art_demo_prd_current",
      "kind": "prd",
      "local_path": "prd/current.md",
      "feishu_node_token": "docx_xxx",
      "feishu_url": "https://...",
      "local_sha256": "...",
      "feishu_revision": "rev_3",
      "publish_version": 3,
      "sync_state": "clean"
    }
  ]
}
```

### 8.2 Outbox

本地仍然需要 outbox，保证失败可恢复：

```text
.pmagent/sync/
  artifacts.json
  state.json
  outbox/
    evt-*.json
  acked/
  failed/
  conflicts/
```

事件示例：

```json
{
  "schema_version": 1,
  "event_id": "evt_20260430_001",
  "workspace_id": "demo",
  "artifact_id": "art_demo_prd_current",
  "action": "update_doc",
  "local_path": "prd/current.md",
  "local_sha256": "...",
  "base_revision": "rev_2",
  "created_at": "2026-04-30T10:00:00+08:00"
}
```

写飞书成功后再 ACK。不要只因为本地命令发出请求就认为同步成功。

### 8.3 发布流程

```text
1. Agent / 用户修改本地 markdown
2. PMAgent 计算 sha256
3. 写 outbox event
4. FeishuFileBackend 创建或更新 Docs
5. 更新最小索引表 Artifacts / Workspaces
6. 写 SyncEvents ack
7. 更新 artifacts.json
8. 必要时发 IM 摘要
```

### 8.4 拉取流程

V1 拉取的对象不是飞书正文，而是：

- comments；
- suggestion status；
- feedback；
- conflict 信号；
- 分析 Agent 生成的 Suggestions；
- dev feedback。

拉回本地后统一变成 inbox item：

```text
workspaces/<workspace>/inbox/pending/item-*.json
```

不要直接改 `Requirement.md`、`prd/current.md` 或 `dev/dev-plan.md`。

## 9. 编辑权模型

### 9.1 默认规则

| 场景 | V1 处理 |
|---|---|
| Agent 修改 PRD | 改本地 `prd/current.md`，再发布到飞书 |
| 人在飞书评论 PRD | 拉回本地 inbox |
| 人在飞书正文直接改 PRD | 生成 `remote_edit_detected` / `sync_conflict` |
| 分析 Agent 提出建议 | 写 `Suggestions`，拉回 inbox |
| 用户接受建议 | 本地执行对应 skill 或人工修改，再发布 |
| 研发侧发现 PRD 缺口 | 写 dev feedback / inbox，不直接改 PRD |

### 9.2 为什么不让飞书正文直接双向同步

双向正文同步会立刻引入这些问题：

- 飞书 block 格式和 markdown 格式不完全等价；
- 人工编辑可能破坏 metadata；
- Agent 和人同时改同一段时需要复杂 merge；
- 飞书修订历史不等于 Git diff；
- 失败重试可能重复覆盖；
- 测试很难稳定。

因此 V1 应把飞书当作发布层和评论层，而不是任意编辑源。

## 10. 分析 Agent 如何让主流程和 dev 越用越聪明

分析 Agent 的输入不是服务器看板，而是飞书文件层里的全部 PM / dev 文件，加上最小索引表中的机器索引。

它应该读取：

- `Requirement.md`；
- `workspace-summary.md`；
- `research/`；
- `strategy/`；
- `decisions/`；
- `prd/current.md` 和 PRD versions；
- `dev/dev-plan.md`；
- `dev/slices/*.md`；
- `dev/runs/**` 的执行摘要、测试摘要、blockers、decisions；
- `dev/qa/*.md`；
- `dev/lessons/*`；
- 最小索引表中的 artifact hash、sync state、suggestion、feedback 和 lesson 状态。

它不读取 GitHub 代码全文作为主要输入。代码层问题通过 dev 文档、PR 链接、commit、diff summary、test result 和 blocker 摘要进入飞书文件层。

### 10.1 输出不是总结，而是可路由建议

分析 Agent 不应该只写自然语言总结，而要输出能进入 PMAgent inbox 的结构化 suggestion。

建议至少包含：

```json
{
  "schema_version": 1,
  "suggestion_id": "sug_001",
  "scope": "mainflow",
  "problem_type": "missing_research",
  "title": "补充竞品证据后再收敛 PRD",
  "reason": "PRD 中的市场判断没有关联 research 证据。",
  "evidence": [
    {
      "local_path": "prd/current.md",
      "feishu_url": "https://...",
      "sha256": "...",
      "summary": "第 2 节把用户痛点作为事实，但 research/ 下没有对应证据。"
    }
  ],
  "mapped_to": {
    "flow_area": "research",
    "artifact": "research/research-log.md"
  },
  "recommended_action": "run_research",
  "status": "pending"
}
```

### 10.2 建议要映射回流程位置

每条建议都必须回答两个问题：

```text
哪里有问题？
这个问题属于主流程或 dev 的哪个环节？
```

推荐映射表：

| 发现的问题 | 映射位置 | 推荐动作 |
|---|---|---|
| 需求目标含糊 | Requirement | clarify / rewrite requirement |
| 事实判断缺证据 | Research | research |
| 关键取舍未拍板 | Decisions | debate / write decision |
| PRD 验收标准不可测 | PRD | challenge-prd / rewrite PRD |
| PRD 与 dev-plan 不一致 | Dev Readiness | update dev-plan |
| slice 太大或不是用户可观察增量 | Slice | split slice |
| 测试只锁实现细节 | Dev Tests | rewrite public behavior tests |
| run evidence 缺失 | Dev Run | rerun / add evidence |
| blocker 暗示 PRD 缺口 | Mainflow inbox | product decision |
| lesson candidate 证据不足 | Lessons | defer / request evidence |
| 重复出现同类失败 | Lessons / Process | promote accepted lesson |
| 外部环境持续变化 | Observation | observation |

### 10.3 同时覆盖主流程和 dev

分析 Agent 的价值在于跨文件看问题，而不是只检查某一份 PRD。

它应该能提出这些类型的建议：

- 主流程建议：需要澄清、research、debate、observation、补 decision、PRD 回炉；
- dev 建议：dev-plan 不完整、slice 拆分错误、测试口径错误、run evidence 不足、blocker 需要回流；
- 跨层建议：PRD 说的目标和 slice 做的东西不一致，dev 发现的约束没有回写 decision，QA 失败说明验收标准缺失；
- 经验建议：哪些 lesson candidate 值得晋升，哪些经验太泛或证据不足。

### 10.4 分析 Agent 不直接执行

分析 Agent 只做诊断和建议，不直接修改文件，也不直接运行 research / debate / observation / dev。

正确闭环是：

```text
分析 Agent 读取飞书文件层
  -> 写 Suggestions
  -> PMAgent pull 到本地 inbox
  -> 用户或外部 Agent accept / ignore / defer
  -> 接受后由主流程或 dev 侧修改本地文件
  -> 再发布到飞书
  -> 分析 Agent 下一轮基于新文件继续判断
```

这就是“越用越聪明”的核心：不是 Agent 自动替系统做决定，而是每轮建议、反馈、run evidence 和 lesson review 都被结构化留下来，后续分析能利用这些历史证据。

## 11. 研发侧文档如何融入

### 11.1 PRD 到 dev-plan

当 `prd/current.md` 稳定后，进入 dev readiness：

```text
prd/current.md
  -> dev/dev-plan.md
  -> dev/slices/SL-001.md
  -> dev/runs/...
  -> dev/qa/...
  -> dev/lessons/...
```

`dev/dev-plan.md` 应包含：

- PRD 链接；
- 产品目标；
- 工程边界；
- 不做什么；
- 领域语言；
- 关键模块和风险；
- 数据 / API / UI / 权限的实现判断；
- 测试策略；
- slice 拆分顺序；
- first AFK slice；
- 需要人工判断的事项。

飞书中对应 `05-Dev/dev-plan`。

### 11.2 Slice 文档

每个 slice 是研发侧最重要的协作文件。

本地：

```text
dev/slices/SL-001.md
```

飞书：

```text
05-Dev/slices/SL-001
```

建议模板：

```markdown
# Slice SL-001: <标题>

## Goal

## User Story

## Product Context

- PRD:
- Requirement:
- Decisions:

## What To Build

## Acceptance Criteria

## Public Behavior Tests

## Codebase

- codebase_id:
- base_commit:
- branch:
- worktree_path:

## Owned Paths

## Shared Paths

## Commands

## Out Of Scope

## Handoff Notes
```

对应索引表 `Slices` 记录保存结构化字段，飞书 Docs 保存可读正文。

### 11.3 Codebase registry

本地：

```text
dev/codebases.json
```

示例：

```json
{
  "schema_version": 1,
  "codebases": [
    {
      "id": "pmagent",
        "github_url": "https://github.com/<org>/<repo>",
        "local_root": "C:/Users/20663/Desktop/pmagent/pmagent",
      "vcs": "git",
      "base_branch": "main",
      "test_commands": ["pytest"],
      "agent_instructions": ["AGENTS.md"]
    }
  ]
}
```

飞书 `Codebases` 只保存 GitHub 链接、分支、提交和本地可选路径，不保存代码。

### 11.4 Run evidence

研发侧 Agent 执行 slice 后，必须产出 run evidence：

```text
dev/runs/SL-001/run-20260430-001/
  run.json
  touched-files.json
  commands.jsonl
  test-results.json
  decisions.md
  blockers.md
  diff-summary.md
  lesson-candidates.jsonl
```

飞书中只需要镜像摘要：

- `diff-summary.md`；
- `decisions.md`；
- `blockers.md`；
- test result 摘要；
- CI / 日志链接；
- lesson candidates 摘要。

这样 PM 和分析 Agent 可以复盘研发过程，但不会把飞书变成代码仓库或日志仓库。

### 11.5 研发反馈回流

研发侧发现 PRD 或 slice 有问题时，不直接改 PRD，而是写回：

```text
dev feedback
  -> inbox
  -> accept / ignore / defer
  -> 修改 Requirement / PRD / decision / dev-plan
  -> 重新发布到飞书
```

典型反馈类型：

- PRD 缺少失败态；
- 验收标准不可测；
- slice 太大；
- API 边界不清；
- 权限模型缺失；
- 测试策略不适合锁定用户行为；
- 需要人工产品决策。

## 12. 经验沉淀如何进入文件体系

研发经验不要直接写进 `AGENTS.md` 或 prompt。

推荐流程：

```text
lesson-candidates.jsonl
  -> 飞书 LessonCandidates
  -> 分析 Agent 去重 / 聚类 / 补证据
  -> LessonReviewSuggestions
  -> 本地 inbox
  -> accept / ignore / defer
  -> dev/lessons/accepted-lessons.md
  -> memory/global-candidates/
```

只有 review 后接受的经验才进入长期记忆。

候选经验必须绑定证据：

```json
{
  "kind": "test_gotcha",
  "title": "旧 workspace schema 需要自动迁移",
  "evidence": {
    "slice_id": "SL-001",
    "run_id": "run-20260430-001",
    "test_command": "pytest tests/test_init_upgrade.py",
    "related_files": ["src/pmagent/current_state.py"]
  },
  "confidence": "medium",
  "applies_to": ["current_state", "schema_migration"]
}
```

这样后续生成 slice 时可以检索：

- 当前 slice 触碰哪些模块；
- 历史上这些模块有哪些失败模式；
- 哪些经验被接受；
- 哪些经验被拒绝；
- 应该提前补哪些测试。

## 13. FeishuFileBackend 模块边界

建议把飞书文件层实现成 backend，而不是把飞书 API 调用散落在 CLI 里。

接口形态：

```python
class FileLayerBackend:
    def ensure_workspace_tree(self, workspace): ...
    def publish_artifact(self, artifact, content): ...
    def update_artifact_index(self, artifact): ...
    def pull_feedback(self, workspace): ...
    def pull_suggestions(self, workspace): ...
    def record_sync_event(self, event): ...
```

`FeishuFileBackend` 负责：

- 创建 Wiki / Docs 节点；
- markdown 到飞书文档的转换；
- 更新最小索引表；
- 保存飞书 URL / node token / revision；
- 读取 comments / suggestions / feedback；
- 做 rate limit、retry、backoff；
- 把 API 错误结构化写回本地 diagnostics。

它不负责：

- 决定 PRD 内容；
- 合并冲突；
- 修改代码；
- 自动接受 suggestion；
- 替代本地 `current-state.json`。

## 14. MVP 落地顺序

### Step 1：本地文件体系补齐

- 在 workspace scaffold 中加入 `dev/` 目录；
- 增加 `dev/dev-plan.md`、`dev/slices/`、`dev/runs/`、`dev/qa/`、`dev/lessons/`；
- 增加 `dev/codebases.json`；
- 增加 artifact registry；
- 保留 outbox / inbox。

### Step 2：飞书文件树和最小索引表

- 创建 PMAgent Wiki 根空间；
- 创建 Projects / Workspaces 文档树；
- 建 `Workspaces`、`Artifacts`、`SyncEvents` 三张最小索引表；
- 先只做本地到飞书发布；
- 不做飞书正文反向覆盖。

### Step 3：PM artifact 发布

- 发布 `Requirement.md`；
- 发布 `workspace-summary.md`；
- 发布 `prd/current.md`；
- 发布 `decisions/`、`research/`；
- 验证重复发布幂等。

### Step 4：研发文档发布

- 生成并发布 `dev/dev-plan.md`；
- 生成并发布 `dev/slices/*.md`；
- 写 `Codebases`、`Slices`；
- slice 执行后发布 run summary、test summary 和 blockers。

### Step 5：feedback / suggestion 回流

- 飞书 comments / Suggestions 拉成本地 inbox；
- 本地 accept / ignore / defer；
- 写回飞书 Feedback；
- 不自动改 canonical 文件。

### Step 6：分析 Agent 诊断

- 分析 Agent 读取飞书文件层和最小索引表；
- 写结构化 Suggestions；
- 对 lesson candidates 做二次复盘；
- 结果仍走 inbox。

### Step 7：后续基础设施增强

后续再补：

- 分析任务调度；
- API 限流队列；
- 错误审计；
- 自建 analyzer。

## 15. 验收标准

第一版可以用这些标准判断是否跑通：

1. 新建 workspace 后，本地和飞书都能生成稳定目录；
2. `Requirement.md`、`prd/current.md`、`workspace-summary.md` 能发布到飞书；
3. 最小索引表 `Artifacts` 能查到每个 artifact 的本地路径、飞书 URL、hash 和 revision；
4. 重复发布不会产生重复主记录；
5. 飞书 API 失败时，本地主流程不被阻塞，并能看到结构化错误；
6. 飞书正文被人工改动时，不自动覆盖本地，而是进入 conflict / inbox；
7. `dev/dev-plan.md` 和 `dev/slices/*.md` 能成为飞书文件层的一部分；
8. slice 能记录 codebase、branch、base commit、owned paths 和 test commands；
9. 研发 run evidence 能发布摘要到飞书；
10. suggestion 和 dev feedback 能从飞书回到本地 inbox；
11. accept / ignore / defer 能写回飞书；
12. 代码仍只由 GitHub 管理；
13. 分析 Agent 能把建议映射到主流程或 dev 的具体文件和流程位置。

## 16. 最终产品表述

推荐表述：

```text
PMAgent 第一版以飞书作为文件协作层。
飞书保存团队可见的需求、PRD、决策、研发计划、slice、测试摘要和经验复盘。
PMAgent 本地 workspace 是 Agent 可执行的工作副本和协议账本。
代码层在 GitHub，研发侧通过 dev-plan、vertical slice、run evidence 和 lesson review 接入 PMAgent。
分析 Agent 读取飞书上的全部主流程和 dev 文件，持续提出映射到流程位置的建议。
V1 暂不做看板层，只保留必要索引、同步账本和建议记录。
```

不推荐表述：

```text
飞书完全替代 PMAgent server。
飞书正文是可被任意双向同步的唯一源。
PMAgent 接管代码仓库。
分析 Agent 自动修改 PRD 或自动晋升经验。
```

## 17. 结论

当前最稳妥的设计是：

```text
飞书文件层优先；
表格只做机器索引和同步账本；
本地保留 Agent 工作副本和同步账本；
研发文档统一进入 workspace/dev/；
代码层归 GitHub；
分析 Agent 读取飞书全部文件并输出可路由建议；
所有远端变化先进 inbox；
服务器看板暂不做。
```

这样可以先验证最核心的 PM-to-dev 文件闭环，让主流程和 dev 都通过结构化建议、反馈和经验复盘越用越聪明，同时保留后续演进到自建服务器或完整看板的空间。
