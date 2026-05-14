# PM Agent 三层协作最终版详细修改文档

> 2026-04-30 修订提示：本文仍保留较多早期“服务器同步 / 看板 / server suggestions”实现设想，当前不能直接照此实施。最新方向是：V1 暂不做服务器侧看板层；飞书作为文件协作层，同步主流程和 dev 的全部文件；飞书表格只做机器索引、同步账本、建议和反馈记录；代码层在 GitHub；分析 Agent 读取飞书文件层并把问题映射回 Requirement、Research、Decision、PRD、Dev Readiness、Slice、Run、QA 或 Lessons。实施前应以 `pmagent-feishu-file-layer-dev-doc-design.md` 和 `pmagent-current-feishu-claw-dev-slice-plan.md` 为准，再回头重写本文中的 server sync / kanban 章节。

> **PM Agent 不是 Agent Runner，也不是靠大量 CLI 驱动的 PM 软件；PM Agent 是嵌在 Claude Code / Codex / Kiro 等外部 Agent CLI 里的工作流协议、文件协议、状态协议和协作规范层。**

## 1. 一句话结论

PM Agent 应从当前的：

```text
mode 驱动的本地 PM 流程 CLI
```

改成：

```text
外部 Agent 可读取和执行的 PM 工作流协议层
  + 本地文件状态协议
  + 统一 inbox/review 协议
  + 服务器同步 / 看板 / 建议卡片
  + PRD 到开发端 dev-plan / slices 的交付协议
```

真正执行 PM 工作的是外部 Agent，例如 Claude Code / Codex。PM Agent 只负责：

- 稳定文件结构；
- 可恢复状态；
- skill 说明和约束；
- readiness / recommendation 的软提示；
- inbox review 边界；
- server sync / kanban / suggestions；
- dev handoff / slices / feedback loop。

---

## 2. 最终三层模型

```text
主流程层 Mainflow
  外部 Agent 根据 skill 文档推进 Requirement / Research / PRD / Decisions / Dev Handoff
        ↕ sync events / suggestion feedback / artifacts
服务器端 Server
  展示看板，存储同步快照，服务端 Agent 分析内容并生成建议卡片
        ↑ 从主流程同步 dev status；建议以 inbox item 回到主流程

主流程层 Mainflow
        ↕ PRD / dev-plan / vertical slices / dev feedback
开发端 Dev
  消费主流程交付的 PRD，拆 dev-plan / vertical slices / tests / QA，
  并把开发中发现的问题回流主流程
```

三层共同协议：

```text
skill_registry
current-state
readiness
recommended_skills
inbox
sync events
dev artifacts
```

---

## 3. 当前代码现状与目标判断

### 3.1 当前保留的正确方向

- `README.md` 已经把 PM Agent 定位成外部 Agent 的辅助层，这个方向继续保留。
- `src/pmagent/skills/steps/*.md` 已经是外部 Agent 工作说明书，不应改成 PM Agent 自己执行。
- Observation 的边界不是“ingest 直接生成 review card”，而是：
  `外部 Agent 搜索/阅读 -> raw-findings.jsonl -> observe ingest -> observations/<project>/files/*.json + index/state -> observe review / inbox 汇总`。
  也就是说，`observe ingest` 只负责可信落盘和更新项目级 observation log；review 是后续读取 unread observations 的独立步骤。
  外部 Agent 检索网页后并不会“天然得到 JSONL”；JSONL 是 PM Agent 要求外部 Agent 产出的交换格式。
  `observe ingest` 的价值正是在这里：把不可信的 Agent 输出当成输入，做格式校验、字段规范化、URL 校验、canonical observation
  artifact 写入和 run 审计记录。它不负责搜索，也不负责判断用户是否接受这些发现。
- Debate 已经有 artifact 模型：`context/debates/<topic>/status.json / synthesis.md / review.json`，可接入 inbox。
- `src/pmagent/executors/` 可继续服务 observation / debate / server-side helper，但不是主流程中心。

### 3.2 当前必须删除的 mode 偏差

这些运行时概念要移除或迁移到 legacy docs：

```text
mode
route_mode
mode_skill_path
workspace_mode_enum
skill_navigation.modes
Current Mode
_mode_skill_path()
_normalized_mode()
zero-to-one 默认回退
conviction-forge 路由
iteration -> zero-to-one 归一化
```

当前三套 mode：

```text
src/pmagent/skills/modes/zero-to-one/
src/pmagent/skills/modes/conviction-forge/
src/pmagent/skills/modes/iteration/
```

最终都不再作为运行时入口。有价值内容拆到 step skill 或 `docs/legacy/`。

---

## 4. 核心数据流

旧数据流：

```text
mode -> phase -> active_step -> next_recommended_step
```

新数据流：

```text
skill registry
  -> 外部 Agent 选择并读取 skill 文档
  -> 外部 Agent 修改 artifacts / 写 state patch
  -> PM Agent 刷新 current-state / readiness / inbox
  -> PM Agent 生成 recommended_skills
  -> 外部 Agent 展示给用户，由用户决定下一步
```

关键点：

- `recommended_skills` 是软建议，不是强制 gate；
- readiness 可以参与推荐，但不能反向绑架 Agent 提问；
- 用户可以跳过 research 直接 write-prd；
- observation / debate / research 可以是 async skill，但仍然是用户可选择调用。

---

## 5. 核心概念最终定义

### 5.1 skill registry

不是 runner。

职责：

- 列出可用 skill；
- 指向 skill 文档；
- 声明 reads / writes / must_not_mutate；
- 标记 skill 类型：`mainflow / async / review / dev / server / legacy`；
- 提供 `recommended_next` 但不强制；
- 给 `recommend_skills()` 和服务器看板提供 metadata。

### 5.2 skill

skill 是外部 Agent 的工作协议：

```text
告诉外部 Agent：
  - 当前工作面解决什么问题
  - 应该读哪些文件
  - 可以写哪些 artifact
  - 哪些 canonical 文件不能直接改
  - 什么时候必须让用户确认
  - 完成后如何写 state patch
  - 完成后可能推荐哪些下一步
```

不要新增：

```text
pmagent skill run <skill-id>
```

因为 skill 的执行者是外部 Agent，不是 PM Agent。

### 5.3 active_skill

表示外部 Agent 当前围绕哪个 skill 工作。

它不是：

```text
PM Agent 正在执行哪个 skill
```

而是：

```text
外部 Agent 声明：我现在按哪个 skill 文档组织本轮工作
```

示例：

```json
{
  "active_skill": "write-prd",
  "active_skill_started_at": "2026-04-28T10:00:00Z",
  "active_skill_reason": "用户要求基于当前 Requirement 生成 PRD",
  "updated_by": "codex"
}
```

### 5.4 recommended_skills

软推荐。所有推荐默认：

```json
"required": false
```

推荐对象结构：

```json
{
  "id": "research",
  "label": "调研",
  "reason": "PRD 中存在市场判断，但缺少 evidence。",
  "priority": 70,
  "confidence": "medium",
  "required": false,
  "skill_path": "skills/steps/do-research/skill.md",
  "source": "rule:prd-unsupported-claim"
}
```

### 5.5 inbox

统一 review surface。

所有这些内容都进入 inbox：

```text
observation candidates
debate synthesis
server suggestions
dev feedback
candidate review
sync conflicts
```

不再维护独立顶层 `server_suggestions` 状态。服务器建议只是：

```json
{
  "kind": "server_suggestion"
}
```

### 5.6 phase

phase 保留，但只是看板分组和状态摘要，不是 mode，也不是强制流程。

phase 的写入方式：

```text
优先从 active_skill 推导；
active_skill 为空时从 artifacts/readiness/dev/inbox 推导；
外部 Agent 一般不直接写 phase，除非用 state patch 显式覆盖。
```

---

## 6. `recommended_skills` 生成逻辑

### 6.1 生成原则

`recommend_skills(repo_root, state, registry)` 的输入：

- artifacts snapshot；
- readiness；
- inbox summary；
- active_skill；
- dev state；
- server sync state；
- skill registry metadata。

输出规则：

1. 先生成候选；
2. 去重；
3. 按 priority 排序；
4. 最多返回 5 个；
5. 全部 `required=false`；
6. 不得因为 readiness 分数低而强制阻止用户进入下一步；
7. readiness 只影响“推荐理由”和“排序”，不决定用户必须做什么。

### 6.2 推荐规则表

| Priority | 条件 | 推荐 skill | reason | 说明 |
|---:|---|---|---|---|
| 100 | `inbox.count > 0` | `review-inbox` | 有待确认内容 | review 永远优先展示，但仍不强制 |
| 95 | 存在 sync conflict | `review-inbox` | 服务器/本地有冲突需要处理 | conflict 作为 inbox item |
| 90 | 无 workspace 或 workspace 未初始化 | `workspace-init` | 缺少工作区 | 这是 protocol setup，不是 PM skill |
| 85 | `Requirement.md` 不存在 | `clarify` | 尚未形成需求共识 | 读 `write-requirement` skill |
| 80 | clarifying readiness 低或 open questions 多 | `clarify` | 需求仍有关键不确定性 | 只建议继续澄清 |
| 75 | Requirement 存在、但 research evidence 很少，且领域/竞品/约束不明确 | `research` | 需要补证据 | 可跳过 |
| 72 | 存在高风险 tradeoff、互斥方案或价值判断冲突 | `debate` | 适合并行辩论 | async skill |
| 70 | 需要外部市场/竞品/用户/技术变化信号 | `observation` | 适合观察旁路 | async skill |
| 68 | Requirement 存在且 PRD 不存在 | `write-prd` | 可以生成 PRD | research 不作为硬前置 |
| 64 | PRD 已存在但未被挑战 | `challenge-prd` | 适合做 PRD 挑战 | 可跳过 |
| 60 | PRD 存在且 dev-plan 不存在 | `dev-readiness` | 可以进入开发准备度检查 | 对接 dev 端 |
| 58 | dev-plan 存在但 slices 不存在 | `dev-readiness` | 继续拆 vertical slices | `dev-slices` 第一版并入 `dev-readiness`，不单独推荐 |
| 55 | dev feedback 指出 PRD 不可测/矛盾 | `write-prd` 或 `clarify` | 开发反馈需要回流 | 由 feedback kind 决定 |
| 45 | 有 accepted observation 且未生成 maintenance draft | `apply-maintenance` | 观察结果可进入维护 | 只在维护场景推荐 |
| 30 | 所有主 artifact 齐全且无 pending | `export-devpack` | 可导出开发包 | 工具型建议 |

### 6.3 伪代码

```python
def recommend_skills(repo_root: Path, *, state: dict, registry: dict | None = None) -> list[dict]:
    registry = registry or load_skill_registry(repo_root)
    candidates: list[dict] = []

    def add(skill_id: str, *, reason: str, priority: int, source: str, confidence: str = "medium"):
        skill = get_skill_from_registry(registry, skill_id)
        if not skill:
            return
        candidates.append({
            "id": skill_id,
            "label": skill.get("label", skill_id),
            "reason": reason,
            "priority": priority,
            "confidence": confidence,
            "required": False,
            "skill_path": skill.get("skill_path"),
            "source": source,
        })

    inbox = state.get("inbox") or {}
    artifacts = state.get("artifacts") or {}
    readiness = state.get("readiness") or {}
    dev = state.get("dev") or {}

    if int(inbox.get("count") or 0) > 0:
        add("review-inbox", reason="存在待 review 的建议/反馈/冲突。", priority=100, source="rule:inbox-pending")

    if not artifacts.get("requirement", {}).get("exists"):
        add("clarify", reason="尚未形成 Requirement.md。", priority=85, source="rule:missing-requirement")

    if readiness.get("phase") == "clarifying" and readiness.get("score", 0) < 0.75:
        add("clarify", reason="需求澄清评分偏低，建议继续补关键问题。", priority=80, source="rule:low-clarity")

    if artifacts.get("requirement", {}).get("exists") and not artifacts.get("prd", {}).get("canonical_path"):
        add("research", reason="已有需求共识，可选补充调研证据。", priority=75, source="rule:requirement-before-prd")
        add("write-prd", reason="已有需求共识，可以直接生成 PRD。", priority=68, source="rule:requirement-before-prd")

    if artifacts.get("prd", {}).get("canonical_path") and not dev.get("dev_plan_path"):
        add("challenge-prd", reason="PRD 已存在，建议挑战风险。", priority=64, source="rule:prd-before-dev")
        add("dev-readiness", reason="PRD 已存在，可进入开发准备度检查。", priority=60, source="rule:prd-before-dev")

    return dedupe_sort_and_cap(candidates, limit=5)
```

注意：实际实现要把 “调研证据很少 / 高风险 tradeoff / 需要 observation” 拆成小 helper，例如：

```python
_has_research_evidence(...)
_has_unresolved_tradeoff(...)
_has_external_signal_need(...)
_has_dev_feedback(...)
```

---

## 7. `active_skill` 写入机制

### 7.1 不能靠 parse markdown 隐式写入

旧文档说 `active_skill` 从 `summary_hints.get("active_skill")` 来，这不够闭环。外部 Agent 不应该为了改状态去猜 markdown 格式。

### 7.2 新增通用 state patch 协议

新增 CLI：

```text
pmagent state patch --workspace <workspace> --patch-file <json> [--updated-by <agent>]
```

它只是状态协议工具，不是 skill runner。

patch 示例：

```json
{
  "active_skill": "write-prd",
  "active_skill_reason": "用户要求基于当前 Requirement 生成 PRD",
  "active_skill_started_at": "2026-04-28T10:00:00Z"
}
```

完成时：

```json
{
  "active_skill": null,
  "last_completed_skill": {
    "id": "write-prd",
    "completed_at": "2026-04-28T10:30:00Z",
    "artifacts": [
      "workspaces/demo/prd/current.md"
    ]
  }
}
```

可选增加 convenience wrapper：

```text
pmagent state set-active-skill --workspace <workspace> <skill-id>
pmagent state clear-active-skill --workspace <workspace>
```

但文档和 Agent 心智里只强调：

```text
state patch = 外部 Agent 声明当前工作面
```

不是：

```text
pmagent 执行 skill
```

### 7.3 active_skill 校验

`state patch` 应校验：

- `active_skill` 必须存在于 skill registry；
- 如果 skill 声明 `writes`，patch 不能假装完成不存在的 artifact；
- 如果 patch 触及 `prd/current.md`、`Requirement.md` 这类 canonical 文件，要走现有 hooks / guard。

---

## 8. `phase` 推导规则

phase 不再从 mode 继承，也不作为流程限制。它只用于：

- status 展示；
- server kanban 分组；
- recommended_skills 排序；
- 用户快速理解项目在哪个区间。

### 8.1 active_skill -> phase

| active_skill | phase |
|---|---|
| `clarify`, `write-requirement` | `clarifying` |
| `research`, `do-research`, `do-competitive-analysis` | `researching` |
| `debate` | 保持原 phase；如果无 phase，则按 artifact 推导 |
| `write-strategy`, `write-decision`, `write-prd`, `challenge-prd`, `write-testcase` | `prd` |
| `dev-readiness`, `export-devpack` | `dev` |
| `run-observation`, `candidate-review`, `apply-maintenance` | `maintaining` 或保持原 phase |

### 8.2 artifact -> phase

当 `active_skill` 为空：

| artifact 状态 | phase |
|---|---|
| 无 `Requirement.md` | `clarifying` |
| 有 `Requirement.md`，无 PRD，research evidence 少 | `researching` 或 `clarifying`，由 readiness 决定 |
| 有 `Requirement.md`，无 PRD，但 readiness 高 | `prd` |
| 有 PRD，无 `dev/dev-plan.md` | `prd` |
| 有 `dev/dev-plan.md` 或 slices | `dev` |
| 有 accepted observation / maintenance draft | `maintaining` |

实现建议：

```python
def infer_phase_from_state(state: dict, registry: dict) -> str | None:
    active_skill = state.get("active_skill")
    if active_skill:
        phase = registry_phase_for(active_skill)
        if phase:
            return phase
    return infer_phase_from_artifacts(state)
```

---

## 9. skill registry YAML contract

### 9.1 删除旧结构

从 `src/pmagent/scaffold/config/agent-workflow.yaml` 删除：

```yaml
workspace_mode_enum
skill_navigation.modes
default_execution_chain
current_mode_source
current mode required_fields
```

### 9.2 新结构示例

```yaml
schema_version: 2
name: pmagent-skill-first-workflow

state_model:
  active_project_source: "config/projects.json.active_project"
  active_workspace_source: "config/projects.json.active_workspace"
  machine_state_source: "workspaces/<workspace>/.pmagent/current-state.json"
  active_skill_source: "workspaces/<workspace>/.pmagent/current-state.json.active_skill"
  phase_policy: "derived_from_active_skill_then_artifacts"
  phase_enum:
    - clarifying
    - researching
    - prd
    - dev
    - maintaining

skill_registry:
  mainflow:
    clarify:
      label: "需求澄清"
      kind: "mainflow"
      phase: "clarifying"
      skill_path: "skills/steps/write-requirement/skill.md"
      purpose: "澄清需求、记录原始问答、沉淀 Requirement"
      reads:
        - "workspaces/<workspace>/context/clarifying-log.md"
        - "workspaces/<workspace>/Requirement.md"
        - "workspaces/<workspace>/workspace-summary.md"
      writes:
        - "workspaces/<workspace>/context/clarifying-log.md"
        - "workspaces/<workspace>/Requirement.md"
        - "workspaces/<workspace>/workspace-summary.md"
      must_not_mutate:
        - "workspaces/<workspace>/prd/current.md"
      user_confirmation_required:
        - "before_replacing_requirement_consensus"
      outputs:
        - "Requirement.md"
      recommended_next:
        - research
        - write-prd
        - debate

    research:
      label: "调研"
      kind: "mainflow"
      phase: "researching"
      async_capable: true
      skill_path: "skills/steps/do-research/skill.md"
      reads:
        - "workspaces/<workspace>/Requirement.md"
        - "workspaces/<workspace>/workspace-summary.md"
      writes:
        - "workspaces/<workspace>/research/"
        - "workspaces/<workspace>/workspace-summary.md"
      must_not_mutate:
        - "workspaces/<workspace>/prd/current.md"
      outputs:
        - "research/research-log.md"
      inbox_outputs:
        - "research_finding"
      recommended_next:
        - write-prd
        - debate

    write-prd:
      label: "生成 PRD"
      kind: "mainflow"
      phase: "prd"
      skill_path: "skills/steps/write-prd/skill.md"
      reads:
        - "workspaces/<workspace>/Requirement.md"
        - "workspaces/<workspace>/research/"
        - "workspaces/<workspace>/decisions/"
      writes:
        - "workspaces/<workspace>/prd/current.md"
        - "workspaces/<workspace>/workspace-summary.md"
      must_not_mutate:
        - "workspaces/<workspace>/dev/"
      user_confirmation_required:
        - "before_overwriting_existing_prd"
      recommended_next:
        - challenge-prd
        - dev-readiness
        - debate

  async:
    debate:
      label: "Debate"
      kind: "async"
      phase: null
      artifact_root: "workspaces/<workspace>/context/debates/"
      review_surface: "inbox"
      result_to_inbox_kind: "debate_synthesis"

    observation:
      label: "Observation"
      kind: "async"
      phase: "maintaining"
      skill_path: "skills/steps/run-observation/skill.md"
      artifact_root: "observations/<project>/"
      review_surface: "inbox"
      result_to_inbox_kind: "observation_candidate"

  review:
    review-inbox:
      label: "Review Inbox"
      kind: "review"
      skill_path: "skills/review/review-inbox/skill.md"
      purpose: "统一处理 observation/debate/server/dev/conflict items"
      reads:
        - "workspaces/<workspace>/inbox/pending/"
        - "workspaces/<workspace>/inbox/deferred/"
      writes:
        - "workspaces/<workspace>/inbox/accepted/"
        - "workspaces/<workspace>/inbox/ignored/"
        - "workspaces/<workspace>/inbox/deferred/"
      must_not_mutate:
        - "workspaces/<workspace>/Requirement.md"
        - "workspaces/<workspace>/prd/current.md"

  dev:
    dev-readiness:
      label: "开发准备度"
      kind: "dev"
      phase: "dev"
      skill_path: "skills/steps/dev-readiness/skill.md"
      artifact_root: "workspaces/<workspace>/dev/"

  maintenance:
    apply-maintenance:
      label: "Apply Maintenance"
      kind: "maintenance"
      phase: "maintaining"
      skill_path: "skills/maintenance/apply-maintenance/skill.md"
      purpose: "把已接受的 observation/candidate 转成维护草稿或经确认后应用到 canonical artifact"
      reads:
        - "observations/<project>/"
        - "workspaces/<workspace>/maintenance/"
        - "workspaces/<workspace>/prd/current.md"
      writes:
        - "workspaces/<workspace>/maintenance/"
      must_not_mutate:
        - "workspaces/<workspace>/prd/current.md"
      user_confirmation_required:
        - "before_applying_maintenance_to_canonical_prd"
```

---

## 10. 17 个现有 step skills 的归类

当前 `src/pmagent/skills/steps/` 下有 17 个 step skill。最终归类如下：

| Skill | 新 kind | phase | 处理方式 |
|---|---|---|---|
| `write-requirement` | `mainflow` | `clarifying` | 保留，作为 `clarify` 的 skill_path |
| `do-research` | `mainflow/async_capable` | `researching` | 保留，可同步或异步 |
| `do-competitive-analysis` | `mainflow/async_capable` | `researching` | 保留，作为 research 子类 |
| `write-strategy` | `mainflow` | `prd` | 保留，作为 PRD 前策略沉淀 |
| `write-decision` | `mainflow` | `prd` | 保留，写 decisions |
| `write-prd` | `mainflow` | `prd` | 保留，canonical PRD skill |
| `challenge-prd` | `mainflow/review` | `prd` | 保留，PRD 风险挑战 |
| `write-testcase` | `dev/prd` | `dev` | 保留，迁到 dev readiness 旁路 |
| `export-devpack` | `dev/tool` | `dev` | 保留，但只是导出工具，不是默认下一步 |
| `run-observation` | `async` | `maintaining` 或保持原 phase | 保留，接 inbox |
| `candidate-review` | `review` | `maintaining` | 保留，接 inbox |
| `engineering-score` | `review/advisory` | `dev` | 保留，作为 dev-readiness 评分辅助 |
| `generate-options-from-context` | `mainflow/advisory` | `prd` | 从 conviction-forge 拆出，保留为可选发散 skill |
| `solve-from-context` | `mainflow/advisory` | `prd` | 从 conviction-forge 拆出，保留为方案收敛 skill |
| `gen-interaction` | `prototype` | `prd` | 保留，归到 prototype 辅助，不进主线 |
| `generate-prototype` | `prototype` | `prd` | 保留，作为 optional prototype skill |
| `sync-prd-prototype` | `prototype/tool` | `prd` | 保留，作为 PRD/prototype 同步工具 |

新增：

| Skill | kind | phase | 说明 |
|---|---|---|---|
| `dev-readiness` | `dev` | `dev` | 根据 PRD 生成 dev-plan / slices readiness |
| `dev-slices` | `dev` | `dev` | 第一版不单独建 skill，推荐规则并入 `dev-readiness` |
| `review-inbox` | `review` | null | 统一 review surface；服务器建议也通过它处理 |
| `apply-maintenance` | `maintenance` | `maintaining` | 新增，处理 accepted observation/candidate 到维护草稿/确认应用 |

---

## 11. async skill 基础设施

### 11.1 async 的定义

async skill 不是“PM Agent 自己异步执行一切”，而是：

```text
某个工作可以被外部 Agent、现有本地 runner、或服务端 Agent 旁路推进；
结果稍后以 artifact + inbox item 的方式回流主流程。
```

### 11.2 复用现有体系

不重建一套全新 runner。按当前代码复用：

| 子系统 | 现有模块 | 新角色 |
|---|---|---|
| Observation scheduler | `observation/scheduler.py` | 保留，只负责 observation cadence |
| Observation runner | `observation/runner.py` | 保留，产生 run artifact |
| Observation executor | `observation/executor.py` | 保留，调用外部 Agent/工具完成观察 |
| Debate orchestrator | `debate/orchestrator.py` | 保留，生成 debate artifact |
| Debate executors | `debate/executors.py` | 保留，负责 debate 执行配置 |
| Generic executors | `executors/` | 保留，作为底层执行适配 |

新增一个很薄的归一层：

```text
src/pmagent/async_runs.py
```

职责不是执行所有任务，而是把 observation / debate / server analysis 的生命周期统一写进 state/inbox。

### 11.3 async run 状态

```json
{
  "id": "async-...",
  "skill_id": "debate",
  "kind": "debate",
  "status": "running",
  "artifact_root": "workspaces/demo/context/debates/topic-x",
  "created_at": "...",
  "completed_at": null,
  "inbox_item_id": null
}
```

状态枚举：

```text
requested
running
completed
awaiting_review
accepted
ignored
failed
```

### 11.4 result -> inbox

| async result | 触发条件 | inbox kind |
|---|---|---|
| observation candidates | `observe ingest` 后产生 project-level observation files，workspace 有 unread observations | `observation_candidate` |
| debate synthesis | `status.json.state=completed` 且无 review 结果 | `debate_synthesis` |
| server suggestion | server pull 收到 suggestion | `server_suggestion` |
| dev feedback | dev slice 发现 PRD 问题 | `dev_feedback` |
| sync conflict | push/pull 发现 hash/version 冲突 | `sync_conflict` |

Debate 连接方式：

```text
context/debates/<topic>/synthesis.md
context/debates/<topic>/status.json completed
  -> inbox/pending/item-<topic>.json
```

Observation 连接方式：

```text
observations/<project>/files/*.json pending
  -> inbox/pending/item-<observation-id>.json
```

---

## 12. Inbox 统一 review surface

### 12.1 新增模块

```text
src/pmagent/inbox.py
```

职责：

- 汇总 observation pending items；
- 汇总 debate synthesis awaiting review；
- 汇总 server suggestions；
- 汇总 dev feedback；
- 汇总 sync conflicts；
- 提供 list / accept / ignore / defer；
- 把 accepted/ignored 信号写回对应源系统。

### 12.2 本地路径

修正旧文档里的 `inbox/inbox/`，最终结构：

```text
workspaces/<workspace>/inbox/
  pending/
    item-*.json
  accepted/
    item-*.json
  ignored/
    item-*.json
  deferred/
    item-*.json
```

### 12.3 Inbox item

```json
{
  "schema_version": 1,
  "id": "inbox-...",
  "kind": "server_suggestion",
  "title": "建议补充竞品调研",
  "source": "server-agent",
  "artifact_path": "workspaces/demo/server-suggestions/sug-1.json",
  "recommended_skill": "research",
  "status": "pending",
  "created_at": "2026-04-28T10:00:00Z"
}
```

### 12.4 current-state 中的 inbox

```json
{
  "inbox": {
    "count": 3,
    "summary_by_kind": {
      "server_suggestion": 1,
      "debate_synthesis": 1,
      "dev_feedback": 1
    },
    "items": [
      {
        "id": "inbox-...",
        "kind": "server_suggestion",
        "title": "建议补充竞品调研",
        "recommended_skill": "research"
      }
    ]
  }
}
```

不要再有顶层：

```json
"server_suggestions": { ... }
```

### 12.5 CLI

保留少量 review 协议命令：

```text
pmagent inbox list --workspace <workspace>
pmagent inbox accept --workspace <workspace> --id <id>
pmagent inbox ignore --workspace <workspace> --id <id>
pmagent inbox defer --workspace <workspace> --id <id>
```

这些不是主流程 CLI，而是统一 review 协议。

---

## 13. Server sync / Server Agent 设计

### 13.1 第一版边界

第一版服务器只做：

- 接收本地 artifact/event 同步；
- 展示项目 / 需求 / PRD / dev 状态看板；
- 服务端 Agent 读同步快照并生成 suggestion；
- suggestion 下发为 inbox item；
- 收集 accepted / ignored / deferred feedback。

第一版不做：

- 自动改本地 PRD；
- 自动替用户执行 research/debate/observation；
- 自动 fine-tune；
- 自动根据采纳率改 prompt。

### 13.2 技术栈建议

最小可实现：

```text
server/
  pmagent_server/
    app.py              # FastAPI
    db.py               # SQLite for local/single-user; Postgres-ready schema
    models.py
    sync_api.py
    suggestion_api.py
    kanban_api.py
    agent_analyzer.py
    suggestion_policy.md
```

数据库：

```text
V1: SQLite
V1.5: Postgres
```

理由：

- 当前系统本地文件优先；
- SQLite 足够做单机/团队试用；
- schema 设计时避免 SQLite-only 特性，后续可迁 Postgres。

### 13.3 API

```text
POST /api/v1/workspaces/{workspace_id}/events
POST /api/v1/workspaces/{workspace_id}/files
GET  /api/v1/workspaces/{workspace_id}/snapshot
GET  /api/v1/workspaces/{workspace_id}/kanban
GET  /api/v1/workspaces/{workspace_id}/suggestions
POST /api/v1/suggestions/{suggestion_id}/accept
POST /api/v1/suggestions/{suggestion_id}/ignore
POST /api/v1/suggestions/{suggestion_id}/defer
POST /api/v1/agent/analyze
```

### 13.4 Server Agent 分析触发时机

Server Agent 分析不要阻塞本地 push。触发策略：

| 触发 | 行为 |
|---|---|
| 每次成功 push 后 | 服务器返回 ack，并异步 enqueue analyze job；本地 `server_sync.push()` 不等待分析完成 |
| 关键文件变化 | `Requirement.md`、`prd/current.md`、`dev/dev-plan.md`、`dev/slices/*.md` 变化时提高分析优先级 |
| inbox feedback | 用户 accept/ignore/defer suggestion 后，记录反馈并可触发轻量复盘 |
| 定时任务 | 服务器定时扫描长时间未分析或状态停滞的 workspace |
| 手动触发 | UI 或 `POST /api/v1/agent/analyze` 显式触发 |

API 返回可带：

```json
{
  "ack": true,
  "analysis_queued": true,
  "analysis_job_id": "job-..."
}
```

本地同步只关心 event 是否 ack；suggestion 通过后续 pull 进入 inbox。

### 13.5 认证

V1：

```text
Bearer token per workspace/device
```

本地配置：

```text
config/server.json
```

示例：

```json
{
  "enabled": true,
  "base_url": "https://pmagent.example.com",
  "workspace_token_env": "PMAGENT_SERVER_TOKEN"
}
```

token 不写入 workspace artifact。

### 13.6 本地 sync outbox

```text
workspaces/<workspace>/.pmagent/sync/
  state.json
  outbox/
    evt-*.json
  acked/
    evt-*.json
  failed/
    evt-*.json
```

event：

```json
{
  "schema_version": 1,
  "event_id": "evt-...",
  "workspace": "demo",
  "project": "alpha",
  "kind": "file_changed",
  "path": "workspaces/demo/prd/current.md",
  "sha256": "...",
  "base_revision": "rev-123",
  "created_at": "..."
}
```

### 13.7 outbox retention

| 状态 | 策略 |
|---|---|
| pending | 保留直到 ack |
| acked | 移到 `acked/`，保留 30 天或最多 1000 条 |
| failed transient | 指数退避重试 |
| failed permanent | 移到 `failed/` 并生成 inbox item |
| conflict | 不自动合并，生成 `sync_conflict` inbox item |

### 13.8 冲突策略

第一版：

```text
local canonical wins
server is mirror/advisory
```

如果服务器和本地同一路径 hash 不一致：

1. 不自动覆盖本地；
2. 写 `inbox/pending/item-*.json`，kind=`sync_conflict`；
3. `conflicts.py` 负责展示 diff / 建议解决；
4. 用户或外部 Agent 决定 accept local / accept remote / manual merge。

### 13.9 Server Agent 建议卡片

服务器建议本地保存：

```text
workspaces/<workspace>/server-suggestions/
  sug-*.json
```

同时镜像成：

```text
workspaces/<workspace>/inbox/pending/item-*.json
```

这里保留双路径是有意的：

- `server-suggestions/sug-*.json` 是服务器返回的原始建议卡片，便于审计、重新生成 inbox item、同步 feedback；
- `inbox/pending/item-*.json` 是统一 review 入口，只保存 review 所需指针和摘要；
- `current-state.json` 只汇总 inbox，不再暴露顶层 `server_suggestions`。

suggestion card：

```json
{
  "schema_version": 1,
  "suggestion_id": "sug-...",
  "kind": "research",
  "title": "建议补充竞品调研",
  "reason": "PRD 中存在未经证据支持的市场判断。",
  "evidence": [
    {
      "path": "workspaces/demo/prd/current.md",
      "summary": "第 3 节提到竞品优势但无来源。"
    }
  ],
  "recommended_skill": "research",
  "status": "pending",
  "created_at": "..."
}
```

### 13.10 Server Agent “自我优化”边界

第一版只收集信号：

```json
{
  "suggestion_id": "sug-...",
  "feedback_signal": "explicit_user_accept",
  "accepted_at": "...",
  "workspace": "demo",
  "suggestion_policy_version": "v1"
}
```

服务器记录：

- 哪类建议被接受；
- 哪类建议被忽略；
- 建议对应的 evidence；
- 当时的 suggestion prompt/policy version；
- 用户是否点击接受。

第一版不做自动优化。  
后续优化只能是：

```text
offline policy review -> 更新 suggestion_policy.md -> 新 policy version
```

不要第一版就做：

```text
根据单个用户采纳率自动改 prompt
自动 fine-tune
自动改变推荐策略
```

原因：

- 采纳率样本少，容易过拟合；
- 建议很多元，accept/ignore 不等于绝对质量；
- 自动优化会让系统行为不可解释。

---

## 14. `current_state.py` 修改

### 14.1 删除

删除：

```python
def _normalized_mode(...)
```

删除 `_summary_hints()` 中：

```python
"mode": r"- Current Mode:\s*`([^`]+)`",
```

删除 `_default_state()` / `preview_current_state()` 中：

```python
"mode": ...
state["mode"] = _normalized_mode(...)
```

删除：

```python
"active_step"
"next_recommended_step"
```

或迁移为兼容 legacy 字段，不再用于运行时输出。

### 14.2 新 state 字段

```python
{
  "schema_version": 2,
  "project": project,
  "workspace": workspace,
  "phase": inferred_phase,
  "active_skill": None,
  "active_skill_reason": None,
  "last_completed_skill": None,
  "recommended_skills": [],
  "inbox": {
    "count": 0,
    "summary_by_kind": {},
    "items": []
  },
  "skill_runs": {
    "active": [],
    "recent": []
  },
  "async_runs": {
    "active": [],
    "awaiting_review": [],
    "recent": []
  },
  "server_sync": {
    "enabled": False,
    "last_push_at": None,
    "last_pull_at": None,
    "pending_changes": 0,
    "last_error": None
  },
  "dev": {
    "dev_plan_path": None,
    "slices_root": None,
    "slices_count": 0,
    "active_slice": None,
    "blocked_count": 0,
    "feedback_to_prd": []
  },
  "artifacts": artifacts,
  "readiness": readiness,
  "updated_at": utc_now(),
  "updated_by": updated_by
}
```

### 14.3 `skill_runs` 与 `async_runs` 边界

两者都可以出现在 state 里，但职责不同：

| 字段 | 写入方 | 生命周期 | 示例 |
|---|---|---|---|
| `skill_runs` | 外部 Agent 通过 `pmagent state patch` 声明 | 同步工作面，通常跟随一次外部 Agent 会话开始/结束 | `clarify`、`write-prd`、`challenge-prd`、`dev-readiness` |
| `async_runs` | PM Agent 可观察的后台/旁路子系统写入 | 可能跨会话存在，结果最终进入 inbox | `observation`、`debate`、server analysis |

原则：

- `active_skill` 是当前外部 Agent 正在处理的工作面；
- 如果需要审计历史，可同步追加到 `skill_runs.recent`；
- observation / debate / server analysis 不写 `active_skill`，而写 `async_runs`；
- `async_runs` 的完成结果不要直接改 canonical artifact，必须进入 inbox。

第一版可以先实现 `active_skill` + `async_runs`，把 `skill_runs.recent` 作为审计增强项后置。

### 14.4 dev snapshot

```python
def _dev_snapshot(repo_root: Path, workspace: str) -> dict[str, Any]:
    root = workspace_root(repo_root, workspace) / "dev"
    dev_plan = root / "dev-plan.md"
    slices_root = root / "slices"
    slices = sorted(slices_root.glob("*.md")) if slices_root.exists() else []
    return {
        "dev_plan_path": _rel(repo_root, dev_plan) if dev_plan.exists() else None,
        "slices_root": _rel(repo_root, slices_root) if slices_root.exists() else None,
        "slices_count": len(slices),
        "slice_paths": [_rel(repo_root, item) for item in slices],
    }
```

### 14.5 import 位置

不要在 `sync_current_state()` 末尾写函数体内 import。放到文件顶部：

```python
from .skill_registry import load_skill_registry, recommend_skills
from .inbox import build_inbox_snapshot
```

如果担心循环引用，就把 `recommend_skills` 的依赖保持纯函数，不反向 import `current_state.py`。

### 14.6 schema v1 -> v2 自动升级

现有 workspace 可能已经有 `schema_version: 1` 的 `current-state.json`。Step 1 实现时必须保证：

- 读到旧 state 不报错；
- 用 v2 default state 深合并旧 state；
- 删除或忽略旧运行时字段：`mode / active_step / next_recommended_step`；
- 自动补齐 `active_skill / recommended_skills / inbox / async_runs / server_sync / dev`；
- 写回时使用 `schema_version: 2`。

实现上放在 `preview_current_state()` 或专门 helper：

```python
def upgrade_state_schema(state: dict) -> dict:
    if int(state.get("schema_version", 1) or 1) < 2:
        state = migrate_v1_to_v2(state)
    return state
```

---

## 15. CLI 收敛

保留少量协议型 CLI：

```text
pmagent init
pmagent upgrade
pmagent workspace-init
pmagent switch

pmagent status
pmagent next
pmagent review
pmagent resume

pmagent state patch
pmagent inbox list/accept/ignore/defer
pmagent sync status/push/pull
pmagent export
```

保留底层工具型命令：

```text
pmagent observe ingest
pmagent debate start/status/show/review/resolve/_run-topic
```

弱化或合并：

```text
pmagent clarify ...
pmagent research ...
pmagent prd ...
pmagent observe review ...
pmagent debate review ...
```

它们可以作为兼容 helper，但不再是主要心智入口。

### 15.1 `cli_routing.py`

删除：

```python
_mode_skill_path()
route_mode
mode_skill_path
```

`_route_payload()` 返回：

```python
{
    "workspace": payload.get("workspace"),
    "project": payload.get("project"),
    "phase": payload.get("phase"),
    "active_skill": payload.get("active_skill"),
    "guided_view": _guided_view_from_state(payload),
    "readiness": payload.get("readiness"),
    "recommended_skills": payload.get("recommended_skills", []),
    "inbox": payload.get("inbox", {}),
    "server_sync": payload.get("server_sync", {}),
    "dev": payload.get("dev", {}),
    "route_reason": _route_reason_from_state(payload),
    "suggested_surface": _suggested_surface_from_state(payload),
}
```

### 15.2 `presentation.py`

删除 “当前模式”。展示：

```text
当前 skill
当前 phase
推荐 skills
inbox
server sync
dev status
```

推荐 skills 表：

```md
| Skill | 原因 | 强制 | Skill 文档 |
|---|---|---|---|
| research | ... | no | skills/steps/do-research/skill.md |
```

---

## 16. 现有模块去留

| 模块 | 处理 | 新职责 |
|---|---|---|
| `skills_sync.py` | 保留并改写 | 同步 skill registry / scaffold skill docs，不再同步 modes |
| `launchd.py` | 保留 | 作为 macOS background scheduler 安装工具，服务 observation/sync，不进入主流程心智 |
| `weekly.py` | 弱化/保留 | 迁为 scheduled observation/report helper |
| `web_search.py` | 保留 | 作为外部 Agent 或 observation 的底层搜索辅助，不等同 research 主流程 |
| `retrieval.py` | 保留 | 给外部 Agent / server Agent 做 artifact 检索 |
| `linker.py` | 保留 | artifact backlink / cross-reference hygiene |
| `conflicts.py` | 保留并扩展 | 处理 sync conflict inbox item |
| `ops/` | 补文档/脚本 | 放 server 部署、sync daemon、ops runbook |
| `executors/` | 保留 | observation/debate/server helper 的执行适配层 |
| `debate/` | 保留 | 作为 async skill backend，结果进 inbox |
| `observation/` | 保留 | 作为 async observation backend，结果进 inbox |

---

## 17. Dev Readiness / 开发端协议

### 17.1 新增文件

```text
src/pmagent/templates/DEV_PLAN_TEMPLATE.md
src/pmagent/templates/VERTICAL_SLICE_TEMPLATE.md
src/pmagent/skills/steps/dev-readiness/skill.md
```

### 17.2 工作区结构

```text
workspaces/<workspace>/dev/
  dev-plan.md
  slices/
    001-<short-name>.md
  qa-report.md
  feedback/
    feedback-*.json
```

### 17.3 dev-plan.md

```md
# Development Plan

## Source PRD

## Product Goal

## Implementation Decisions

## Testing Decisions

## Deep Module Opportunities

## Domain Language

## Vertical Slices

## Ready for Dev Checklist
```

### 17.4 slice

```md
# Slice 001: <短标题>

## Type

AFK / HITL

## Goal

## User Story

## What to Build

## Acceptance Criteria

## Public Behavior Tests

## Interfaces

## Blocked By

## Out of Scope
```

### 17.5 Dev feedback 回流

开发端发现问题后生成 inbox item：

```json
{
  "kind": "dev_feedback",
  "title": "Slice 001 发现 PRD 验收标准不可测",
  "recommended_skill": "write-prd",
  "artifact_path": "workspaces/demo/dev/slices/001-x.md",
  "status": "pending"
}
```

---

## 18. Export 改造

`src/pmagent/exporter.py` 保留，因为它是文件打包工具，不是 Agent runner。

最终导出：

```text
exports/vN/
  PRD.md
  DEV_CONTEXT.md
  dev-plan.md
  slices/
    001-xxx.md
  MANIFEST.md
```

如果 dev readiness 不存在，不要伪造。  
manifest 写：

```text
Dev readiness: missing
Recommended skill: dev-readiness
```

---

## 19. Tests 改造

### 19.1 当前 174/175 个 tests 的判断

不是所有测试都没用，但大量 tests 现在保护的是旧心智：

```text
mode routing
zero-to-one default
Current Mode presentation
route_mode payload
mode_skill_path payload
```

这些测试会阻止最终架构，必须删或重写。

仍有价值的测试：

- observation ingest/review；
- debate artifact/review/resolve；
- executor timeout/permission；
- hooks 防止未经确认改 canonical PRD；
- init/upgrade 不覆盖用户文件；
- export manifest；
- conflict/retrieval/linker 的底层行为。

### 19.2 删除 / 重写

删除所有断言：

```text
route_mode
mode_skill_path
Current Mode
zero-to-one default
conviction-forge route
iteration normalized
```

### 19.3 新增 tests

```text
tests/test_skill_registry.py
tests/test_skill_recommendations.py
tests/test_skill_first_routing.py
tests/test_state_patch.py
tests/test_inbox.py
tests/test_async_runs.py
tests/test_server_sync.py
tests/test_server_sync_suggestions.py
tests/test_dev_readiness_protocol.py
```

### 19.4 新断言

```python
assert "mode" not in payload
assert "route_mode" not in payload
assert "mode_skill_path" not in payload

assert payload["recommended_skills"]
assert all(item["required"] is False for item in payload["recommended_skills"])
assert payload["recommended_skills"][0]["skill_path"].endswith(".md")

assert payload["inbox"]["count"] == len(payload["inbox"]["items"])
assert payload["inbox"]["summary_by_kind"].get("server_suggestion", 0) >= 0
assert "server_suggestions" not in payload
```

---

## 20. 迁移顺序

虽然最终目标不考虑修改成本，但实现需要顺序，否则会被旧 tests 和旧状态互相卡住。

### Step 1：状态协议先行

- 新增 `skill_registry.py`；
- 新增 `state patch`；
- `current_state.py` 加 `active_skill / recommended_skills / inbox / dev`；
- `sync_current_state()` / `preview_current_state()` 读到 v1 state 时自动升级到 v2 default，不因旧 workspace 报错；
- 先让 `status --json` 能输出新字段。

### Step 2：去 mode 运行时引用

- 改 `cli_routing.py`；
- 改 `presentation.py`；
- 改 `agent-workflow.yaml`；
- 改 scaffold `AGENTS.md`；
- 删除 `_normalized_mode()` / `_mode_skill_path()`。

### Step 3：推荐规则落地

- 实现 `recommend_skills()`；
- 写规则表对应 tests；
- 保证所有推荐 `required=false`。

### Step 4：inbox 统一

- 新增 `inbox.py`；
- observation pending -> inbox；
- debate synthesis -> inbox；
- server suggestions -> inbox；
- dev feedback -> inbox。

### Step 5：async 归一

- 新增 `async_runs.py`；
- 复用 observation/debate 的 runner/orchestrator；
- 不重建大而全 async framework。

### Step 6：server sync skeleton

- 新增 `server_sync.py`；
- outbox/ack/failed/conflict；
- API client；
- suggestion pull / raw suggestion 保存 / inbox item 生成入口；
- 不新增 `server_suggestions.py`：V1 中 suggestion schema/保存/拉取归 `server_sync.py`，review 状态归 `inbox.py`；
- server reference app 可后置，但 API contract 先固定。

### Step 7：dev readiness

- 新增 `dev-readiness` skill；
- 新增 dev templates；
- export 支持 dev-plan/slices；
- dev feedback 回 inbox。

### Step 8：测试清理

- 删旧 mode-era tests；
- 保留底层有价值 tests；
- 新增 skill-first/inbox/server/dev tests。

---

## 21. 最终完成标准

### 21.1 代码搜索标准

运行：

```bash
rg "route_mode|mode_skill_path|workspace_mode_enum|Current Mode|zero-to-one|conviction-forge|iteration" src tests
```

最终不应命中运行时代码、scaffold 或 tests。  
如需保留，只能在：

```text
docs/legacy/
```

### 21.2 行为标准

- `pmagent status --json` 不返回 `mode`；
- `pmagent next --json` 返回 `recommended_skills`；
- `pmagent review --json` 返回 unified inbox；
- 没有 mode 的 workspace 不会默认进入 zero-to-one；
- 外部 Agent 可以通过 `recommended_skills[*].skill_path` 读取 skill 文档继续工作；
- 用户可以跳过 research 直接要求 write-prd；
- debate / observation / server suggestion / dev feedback 都通过 inbox 回流；
- Server Agent 建议被接受后，只记录反馈信号，不自动改策略。

---

## 22. 最终修改文件清单

### 新增

```text
src/pmagent/skill_registry.py
src/pmagent/inbox.py
src/pmagent/async_runs.py
src/pmagent/server_sync.py
src/pmagent/templates/DEV_PLAN_TEMPLATE.md
src/pmagent/templates/VERTICAL_SLICE_TEMPLATE.md
src/pmagent/skills/review/review-inbox/skill.md
src/pmagent/skills/maintenance/apply-maintenance/skill.md
src/pmagent/skills/steps/dev-readiness/skill.md
tests/test_skill_registry.py
tests/test_skill_recommendations.py
tests/test_skill_first_routing.py
tests/test_state_patch.py
tests/test_inbox.py
tests/test_async_runs.py
tests/test_server_sync.py
tests/test_server_sync_suggestions.py
tests/test_dev_readiness_protocol.py
```

### 大改

```text
src/pmagent/current_state.py
src/pmagent/cli.py
src/pmagent/cli_routing.py
src/pmagent/cli_phases.py
src/pmagent/presentation.py
src/pmagent/exporter.py
src/pmagent/scaffold/config/agent-workflow.yaml
src/pmagent/scaffold/AGENTS.md
src/pmagent/skills/README.md
src/pmagent/skills/steps/*/skill.md
tests/test_cli.py
tests/test_cli_subsystems.py
tests/test_init_upgrade.py
tests/test_presentation.py
```

### 保留但改职责

```text
src/pmagent/skills_sync.py
src/pmagent/launchd.py
src/pmagent/weekly.py
src/pmagent/web_search.py
src/pmagent/retrieval.py
src/pmagent/linker.py
src/pmagent/conflicts.py
src/pmagent/ops/
src/pmagent/debate/
src/pmagent/observation/
src/pmagent/executors/
```

### 迁移到 legacy docs 或拆分

```text
src/pmagent/skills/modes/zero-to-one/skill.md
src/pmagent/skills/modes/conviction-forge/skill.md
src/pmagent/skills/modes/iteration/skill.md
```

---

## 23. 最终一句话

PM Agent 最终不应该是“执行 PM 流程的 Agent”，而应该是：

```text
给外部 Agent 使用的 PM 工作流协议层。
```

它暴露：

```text
skill registry
current-state
readiness
recommended_skills
inbox
server sync
dev readiness artifacts
```

外部 Agent 读取这些协议并执行工作；PM Agent 负责把结果变成可恢复、可审查、可同步、可交付的文件系统。
