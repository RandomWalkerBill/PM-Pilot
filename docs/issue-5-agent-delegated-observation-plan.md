# Issue #5 实施方案：统一执行器层 + Agent 委托式 Observation

> 来源 issue：https://github.com/CCDD2022/pm-agent/issues/5  
> Issue 标题：Proposal: 统一执行器层 + Observation Agent-Delegated Execution  
> 核对日期：2026-04-24  
> 建议结论：**方向合理，但需要调整 `observe ingest` 的职责边界后再实现**

## 1. 总结结论

Issue #5 想做两件事：

1. 把 Debate 里的 CLI 执行器从 `src/pmagent/debate/executors.py` 抽成公共模块 `src/pmagent/executors/`。
2. 把 `pmagent observe run` 的搜索执行，从当前 Brave Search 直连，改成委托宿主 Agent（`kiro-cli` / `claude` / `codex`）执行搜索、阅读和筛选。

我判断：**整体方向是合理的，而且和 pmagent 的项目定位一致。**

原因：

- pmagent 本来就是给 Claude Code / Codex / Kiro 这类外部 Agent 使用的工作流骨架。
- 当前 `debate/executors.py` 已经具备通用执行器雏形，不应该长期绑在 debate 子模块里。
- 当前 observation 的搜索质量较弱：主要是 query plan + Brave Search 摘要，不读正文，也没有真正多轮追问。
- 委托 Agent 执行搜索后，可以利用 Agent 自带的 web search / web fetch / 多轮判断能力，质量会更高。

但是，issue 原文里有一个关键点需要修正：

> `observe ingest` 不应该默认直接生成 workspace candidate cards。它应该保留当前项目级 Observation 模型：写入 `observations/<project>/files/obs-*.json`，更新 `index.json` 和 `state.json`，再让现有 `candidate-review` 流程在用户 review 时决定 accept / reject / snooze。

换句话说，新的链路应该是：

```text
Agent 搜索结果
  -> raw-findings.jsonl
  -> pmagent observe ingest
  -> observations/<project>/files/obs-*.json
  -> observations/<project>/index.json
  -> observe review 展示 unread observations
  -> 用户 accept / reject / snooze
  -> candidate-updates/{accepted,rejected,snoozed}
  -> maintenance draft
  -> PRD 更新
```

而不是：

```text
Agent 搜索结果
  -> observe ingest
  -> 直接写 candidate-updates/inbox
```

后者会破坏当前项目级 observation log 与 workspace review 队列之间的边界。

---

## 2. 当前项目架构判断

### 2.1 Debate 执行器现状

相关文件：

```text
src/pmagent/debate/executors.py
src/pmagent/debate/config.py
src/pmagent/debate/orchestrator.py
src/pmagent/cli_debate.py
src/pmagent/scaffold/config/debate-executors.yaml
```

当前 `debate/executors.py` 已有能力：

- `ExecutorResult`
- `DebateExecutorError`
- `run_executor(...)`
- `precheck_executor_plan(...)`
- Claude CLI headless 执行
- Codex CLI headless 执行
- Codex session transcript 解析
- subprocess 统一封装
- Windows 下 Claude 所需 Git Bash 检测

这些能力并不强依赖 debate，只是命名上还在 debate 里。因此抽成公共 `pmagent.executors` 是合理的。

### 2.2 Observation 当前执行链路

相关文件：

```text
src/pmagent/observation/runner.py
src/pmagent/observation/cli.py
src/pmagent/observation/executor.py
src/pmagent/observation/sources.py
src/pmagent/observation/status.py
src/pmagent/observation/cards.py
src/pmagent/observation/scheduler.py
```

当前 `run_live()` 大致流程：

```text
run_live(repo_root, project)
  -> _project_exists()
  -> load_profile()
  -> _project_context_text()
  -> build_query_plan()
       -> 有 OpenAI key 时调模型生成 query plan
       -> 没有时走 fallback query plan
  -> fetch_query_results()
       -> 需要 BRAVE_SEARCH_API_KEY
       -> search_web()
       -> Brave Search 返回 title/url/description/age
  -> 写 observations/<project>/runs/<run_id>/query-plan.json
  -> 写 observations/<project>/runs/<run_id>/raw-findings.jsonl
  -> 写 observations/<project>/files/obs-<run_id>-NN.json
  -> 更新 observations/<project>/index.json
  -> 更新 observations/<project>/state.json
  -> 写 meta.json / decisions.json / summary-write-preview.md
```

重点：当前 `run_live()` 的 canonical 输出是 project 级 observation 文件，不是 candidate cards。

### 2.3 当前 candidate-review 模型

当前 review 链路是：

- `observations/<project>/index.json` 记录所有 observation ids。
- workspace 的 `.pmagent/current-state.json` 记录 seen / pending 状态。
- `pmagent observe review --workspace <workspace>` 展示未读 observation。
- 用户执行 accept / reject / snooze 时，才进入 `candidate-updates/`。

所以：

```text
observations/<project>/files/*.json
```

是项目级外部信号日志。

```text
workspaces/<workspace>/candidate-updates/*
```

是 workspace 级 review / maintenance 工件。

这两个层级不能混淆。

### 2.4 Scheduler 合约

`src/pmagent/observation/scheduler.py` 当前生成的命令类似：

```text
python -m pmagent.cli observe --data-dir <repo_root> run --project <project>
```

Issue #5 说 scheduler 不改，这是对的。应该保持命令不变，只改变 `observe run` 内部执行方式。

---

## 3. 目标架构

### 3.1 新的总流程

建议目标链路：

```text
pmagent observe run --project <project>
  -> plan_only() 生成 observation plan
  -> 如果当前已经在 Agent session 内：
       输出明确 handoff，让当前 Agent 执行 run-observation 协议
     否则：
       resolve_available_backend()
       用 kiro / claude / codex headless 启动 Agent
  -> Agent 执行 web_search / web_fetch / 多轮判断
  -> Agent 只写 raw-findings.jsonl
  -> Agent 调 pmagent observe ingest
  -> ingest 校验并写 canonical observation files/index/state
  -> observe review 后续照旧
```

### 3.2 职责边界

| 层 | 负责 | 不负责 |
|---|---|---|
| Agent backend | 搜索、阅读网页、判断相关性、写 raw findings | 直接改 PRD、直接写 candidate-updates、直接改 canonical state |
| `observe ingest` | 校验 findings、写 observation files、更新 index/state/meta/decisions | 搜索网页 |
| `observe review` | 展示 unread observations，驱动用户 accept/reject/snooze | 自动修改 PRD |
| maintenance | 把 accepted 信号转成 PRD maintenance draft | 接受未经 review 的 raw findings |

这样可以降低 headless Agent 的不可控风险：Agent 负责研究，CLI 负责可信落盘和状态更新。

---

## 4. 分阶段实施计划

## Phase 0：先保护当前行为

在动代码前，先明确要保留的行为：

1. `observe run` 会写 project-level observation files。
2. `observe review` 从 `observations/<project>/index.json` 里读 unread observation ids。
3. candidate cards 是 workspace review 工件，不是 observation run 的默认输出。
4. scheduler 命令形态不变。

建议先确认或补充测试：

- `test_run_live_writes_project_level_observation_files`
- unread / review 相关测试
- scheduler command shape 相关测试

验收：现有测试保持通过。

---

## Phase 1：抽出公共 executor 层

### 4.1 新增目录

新增：

```text
src/pmagent/executors/
  __init__.py
  _subprocess.py
  _claude.py
  _codex.py
  _kiro.py
  registry.py
```

### 4.2 公共 API

`src/pmagent/executors/__init__.py` 建议导出：

```python
@dataclass
class ExecutorResult:
    content: str
    session_id: str

class ExecutorError(RuntimeError):
    pass

def run_executor(
    executor_id: str,
    prompt: str,
    *,
    cwd: Path,
    session_id: str | None = None,
    model: str | None = None,
    schema: dict | None = None,
    timeout_seconds: float | None = None,
    trust_all_tools: bool = False,
) -> ExecutorResult: ...

def precheck_executor(executor_id: str) -> list[dict[str, str]]: ...

def precheck_executor_plan(plan: dict[str, dict[str, object]]) -> list[dict[str, str]]: ...

def is_inside_agent() -> bool: ...

def resolve_available_backend() -> str: ...
```

### 4.3 backend 命名规范

建议统一：

| 输入 | 规范化 ID | 命令 |
|---|---|---|
| `claude` | `claude` | `claude` |
| `codex` | `codex` | `codex` |
| `kiro` | `kiro` | `kiro-cli` |
| `kiro-cli` | `kiro` | `kiro-cli` |

`PMAGENT_AGENT_BACKEND` 应支持：

```text
kiro
kiro-cli
claude
codex
```

### 4.4 从 debate/executors.py 抽代码

迁移建议：

```text
_run_subprocess               -> executors/_subprocess.py
_discover_git_bash            -> executors/_claude.py
_run_claude                   -> executors/_claude.py
_codex session helpers        -> executors/_codex.py
_run_codex                    -> executors/_codex.py
run_executor dispatch         -> executors/registry.py
precheck_executor_plan        -> executors/registry.py
```

然后把 `src/pmagent/debate/executors.py` 改成 thin wrapper：

```python
from pmagent.executors import (
    ExecutorResult,
    ExecutorError as DebateExecutorError,
    precheck_executor_plan,
    run_executor,
)

__all__ = [
    "ExecutorResult",
    "DebateExecutorError",
    "precheck_executor_plan",
    "run_executor",
]
```

这样 `debate/orchestrator.py` 不需要大改。

### 4.5 新增 Kiro executor

新增 `_kiro.py`。

建议命令：

```text
kiro-cli chat --no-interactive
```

如果 `trust_all_tools=True`：

```text
kiro-cli chat --no-interactive --trust-all-tools
```

返回：

```python
ExecutorResult(content=stdout.strip(), session_id=<generated-or-parsed-id>)
```

如果 Kiro 不支持 resume session，就标记为不支持 session，传入 `session_id` 时要么忽略并说明，要么抛清晰错误。建议第一版不支持 resume。

### 4.6 测试

新增：

```text
tests/test_executors.py
```

覆盖：

- Claude argv 构造。
- Codex argv 构造。
- Kiro argv 构造。
- `trust_all_tools` 是否影响 flags。
- `is_inside_agent()` 对以下变量生效：
  - `KIRO_SESSION`
  - `CLAUDE_CODE`
  - `CODEX_SESSION`
  - `PMAGENT_AGENT_MODE`
- `resolve_available_backend()`：
  - 优先使用 `PMAGENT_AGENT_BACKEND`
  - `kiro-cli` 归一成 `kiro`
  - 按优先级 fallback
  - 没有 backend 时给明确错误
- `precheck_executor_plan()`：
  - unsupported executor
  - missing CLI
  - Windows Claude Git Bash 检查

验收命令：

```bash
python -m pytest tests/test_executors.py tests/test_cli_subsystems.py -q
```

---

## Phase 2：配置兼容与迁移

Issue 里想新增：

```text
config/executors.yaml
```

这是合理的，但不能破坏当前的：

```text
config/debate-executors.yaml
```

### 4.7 配置优先级

建议 `debate/config.py` 的优先级：

1. CLI 参数。
2. `config/debate-executors.yaml`。
3. `config/executors.yaml.defaults.debate`。
4. 内置默认值。

也就是说，现有用户不需要迁移也能继续用。

### 4.8 新 scaffold 文件

新增：

```text
src/pmagent/scaffold/config/executors.yaml
```

示例：

```yaml
schema_version: 2

executors:
  claude:
    kind: cli
    command: claude
    supports_session: true
  codex:
    kind: cli
    command: codex
    supports_session: true
  kiro:
    kind: cli
    command: kiro-cli
    supports_session: false

defaults:
  debate:
    defender:
      exec: claude
      model: null
    attacker:
      exec: codex
      model: null
    synthesizer:
      exec: claude
      model: null
  observation:
    backend: auto
    model: null
```

### 4.9 测试

需要更新或新增：

- `tests/test_init_upgrade.py`
- debate config fallback 测试

验收：

```bash
python -m pytest tests/test_init_upgrade.py tests/test_cli_subsystems.py -q
```

---

## Phase 3：拆分 `observe plan` 和 `observe ingest`

这是最关键的一步。

### 4.10 新增 `plan_only()`

在 `src/pmagent/observation/runner.py` 新增：

```python
def plan_only(repo_root: Path, project: str) -> dict[str, object]:
    ...
```

职责：

- 确认 project 存在。
- 确认 observation profile 存在。
- 生成 `run_id`。
- 读取 project context。
- 生成 query hints。
- 读取当前 observation state/profile。
- 创建 run root：

```text
observations/<project>/runs/<run_id>/
```

- 写 `query-plan.json`。
- 写 mode 为 `plan` 的 `meta.json`。
- 返回 JSON payload。

建议输出：

```json
{
  "schema_version": 1,
  "run_id": "20260424T010203Z-abcd1234",
  "project": "alpha",
  "repo_root": "/path/to/data",
  "run_root": "observations/alpha/runs/20260424T010203Z-abcd1234",
  "findings_path": "observations/alpha/runs/20260424T010203Z-abcd1234/raw-findings.jsonl",
  "queries": [
    {
      "kind": "market",
      "query": "alpha market change",
      "count": 4,
      "freshness": "pm"
    }
  ],
  "context": {
    "project_summary": "...",
    "observation_focus": "...",
    "last_run_id": "...",
    "last_run_at": "..."
  },
  "next_command": "pmagent observe ingest --project alpha --run-id 20260424T010203Z-abcd1234 --findings observations/alpha/runs/20260424T010203Z-abcd1234/raw-findings.jsonl"
}
```

注意：

- `plan_only()` 不执行搜索。
- `plan_only()` 不要求 Brave key。
- 可以保留 OpenAI query plan 优化，但不能强依赖 OpenAI。

### 4.11 定义 raw findings JSONL schema

每行一个 JSON object。

建议最小字段：

```json
{
  "kind": "market",
  "query": "alpha market change",
  "title": "Competitor launched new workflow",
  "url": "https://example.com/article",
  "description": "Short summary of why this matters.",
  "age": "2d",
  "evidence": [
    {
      "title": "Source title",
      "url": "https://example.com/article",
      "quote_or_summary": "Grounded evidence summary."
    }
  ],
  "confidence": "medium"
}
```

校验规则：

- 每行必须是 JSON object。
- `title` 或 `description` 至少一个非空。
- `url` 如果存在，必须是 `http` 或 `https`。
- `confidence` 可选，默认 `medium`。
- 无效行默认应导致 ingest 失败，并给出行号。

### 4.12 新增 `ingest_external()`

在 `runner.py` 新增：

```python
def ingest_external(
    repo_root: Path,
    project: str,
    *,
    run_id: str,
    findings_path: Path,
) -> int:
    ...
```

职责：

1. 校验 project/profile。
2. 定位 run root：

```text
observations/<project>/runs/<run_id>/
```

3. 读取并校验 `raw-findings.jsonl`。
4. 如果 findings path 不在 run root 内，复制/规范化到 run root。
5. 写 canonical observation files：

```text
observations/<project>/files/obs-<run_id>-01.json
observations/<project>/files/obs-<run_id>-02.json
```

6. 更新：

```text
observations/<project>/index.json
observations/<project>/state.json
```

7. 写：

```text
observations/<project>/runs/<run_id>/meta.json
observations/<project>/runs/<run_id>/decisions.json
observations/<project>/runs/<run_id>/summary-write-preview.md
```

8. 输出简洁完成信息。

关键要求：

- 默认不要调用 `_write_candidate_cards()`。
- 默认不要写 `candidate-updates/inbox`。
- candidate lifecycle 继续由 `observe review` + accept/reject/snooze 管。

### 4.13 抽出共享写入逻辑

当前 `run_live()` 里已经有很多写 observation files/index/state/meta/decisions 的逻辑。建议抽成内部 helper：

```python
def _write_project_observations_from_findings(
    *,
    repo_root: Path,
    project: str,
    run_id: str,
    started_at: str,
    findings: list[dict[str, object]],
    query_plan: list[dict[str, object]] | None,
    recall: dict[str, object],
    mode: str,
) -> dict[str, object]:
    ...
```

然后：

- 旧 direct retrieval 临时可以复用它。
- 新 `ingest_external()` 也复用它。

这样减少行为偏差。

### 4.14 CLI 新增命令

修改 `src/pmagent/observation/cli.py`：

```text
pmagent observe plan --project <project> --json
pmagent observe ingest --project <project> --run-id <run_id> --findings <path>
```

新增：

```python
def _cmd_plan(args): ...
def _cmd_ingest(args): ...
```

### 4.15 Facade 更新

修改 `src/pmagent/observation/executor.py`，导出：

```text
plan_only
ingest_external
```

同时保留旧导出以兼容测试/外部调用：

```text
build_query_plan
fetch_query_results
run_live
```

### 4.16 Phase 3 测试

新增或扩展：

```text
tests/test_observation_agent.py
```

测试点：

1. `plan_only()` 创建 run directory 并返回 plan payload。
2. `pmagent observe plan --json` 输出合法 JSON。
3. `ingest_external()` 写 project-level observation files。
4. `ingest_external()` 更新 `index.json` 和 `state.json`。
5. `ingest_external()` 拒绝非法 JSONL。
6. `ingest_external()` 不创建 `candidate-updates/inbox`。
7. `observe review` 能看到 ingest 后的 unread observations。

验收：

```bash
python -m pytest tests/test_observation_cli.py tests/test_observation_agent.py -q
```

---

## Phase 4：改造 `observe run` 为 Agent 委托执行

只有在 `plan` / `ingest` 稳定后，才改 `run_live()`。

### 4.17 新 `run_live()` 逻辑

目标伪代码：

```python
def run_live(repo_root: Path, project: str) -> int:
    plan = plan_only(repo_root, project)

    if is_inside_agent():
        print_agent_handoff(plan)
        return 0

    backend = resolve_available_backend()
    result = run_executor(
        backend,
        render_run_observation_prompt(plan),
        cwd=repo_root,
        timeout_seconds=..., 
        trust_all_tools=True,
    )
    return verify_agent_observation_completed(repo_root, project, plan)
```

### 4.18 inside-agent 分支不能只输出 JSON

Issue 原文里写：

```python
print(json.dumps({
    "action": "execute_skill",
    "skill": "run-observation",
    "plan": plan,
}))
return 0
```

这不够。因为 stdout 不会自动让 Agent 执行 skill。

建议普通输出写清楚：

```text
Observation plan created.
run_id=<run_id>
findings_path=<path>

You are already inside an Agent session.
Execute the run-observation protocol:
1. Search/fetch using the plan below.
2. Write JSONL findings to <findings_path>.
3. Run:
   pmagent observe ingest --project <project> --run-id <run_id> --findings <findings_path>

<machine-readable JSON payload follows>
```

如果 `--json`，则输出纯 JSON：

```json
{
  "action": "agent_handoff_required",
  "skill": "run-observation",
  "plan": {...},
  "ingest_command": "..."
}
```

### 4.19 headless prompt

headless prompt 应该非常窄：

```text
You are executing pmagent's run-observation protocol.

Data directory:
<repo_root>

Project:
<project>

Plan JSON:
<plan>

Allowed writes:
- <run_root>/raw-findings.jsonl
- files created by `pmagent observe ingest ...`

Do not edit Requirement.md, PRD files, workspace-summary.md, or candidate-updates directly.
After web research, write raw-findings.jsonl and run:
<ingest_command>

Return a short completion summary including findings_count and run_id.
```

### 4.20 完成后必须验证

headless Agent 返回后，`run_live()` 必须验证：

- `raw-findings.jsonl` 存在。
- `meta.json` 存在。
- `decisions.json` 存在。
- `observations/<project>/state.json.last_run_id == run_id`。
- `observations/<project>/index.json` 包含本次新增 observation ids。

如果验证失败：

- 写失败 metadata。
- 返回非 0 或抛 `SystemExit`。
- 保存 agent stdout/stderr 摘要，方便排查。

### 4.21 Phase 4 测试

测试点：

1. inside-agent 分支只输出 handoff，不调用 `run_executor`。
2. 非 agent 分支会 resolve backend 并调用 `run_executor`。
3. 非 agent 分支能验证成功 ingest。
4. 非 agent 分支在 ingest 未发生时失败。
5. `PMAGENT_AGENT_BACKEND=kiro-cli` 会解析到 `kiro`。

---

## Phase 5：新增 `run-observation` skill

### 4.22 新增文件

新增：

```text
src/pmagent/skills/steps/run-observation/skill.md
```

建议内容结构：

```markdown
# Run Observation

## Purpose

Use the host Agent's web search/fetch capability to execute a pmagent Observation plan,
then hand validated raw findings back to `pmagent observe ingest`.

## Inputs

- Project name
- Plan JSON from `pmagent observe plan --project <project> --json`
- Run root
- Findings path
- Ingest command

## Reads

- `observations/<project>/runs/<run_id>/query-plan.json`
- `projects/<project>/...`
- Workspace summary only as context

## Writes

- `observations/<project>/runs/<run_id>/raw-findings.jsonl`
- Then only through `pmagent observe ingest`

## Must not write directly

- `Requirement.md`
- `prd/**`
- `candidate-updates/**`
- `workspace-summary.md`
- `.pmagent/current-state.json`

## Procedure

1. Read the plan.
2. Search using the query hints.
3. Fetch/read high relevance pages.
4. Add follow-up searches when needed.
5. Write one JSON object per line to `raw-findings.jsonl`.
6. Run the provided ingest command.
7. Report run_id and findings_count.
```

### 4.23 更新文档和 scaffold

需要更新：

```text
src/pmagent/skills/README.md
src/pmagent/scaffold/AGENTS.md
src/pmagent/scaffold/config/agent-workflow.yaml
README.md
```

文档表述要精确：

- 如果 Observation 不再用 Brave，README 不能再说 `observe run` 需要 `BRAVE_SEARCH_API_KEY`。
- 但 `pmagent search` / `pmagent digest` 如果仍用 Brave，则仍然需要 `BRAVE_SEARCH_API_KEY`。
- 不能说整个项目去掉了 OpenAI；只能说 Observation live run 不再强依赖 OpenAI。

---

## Phase 6：处理旧 Brave 路径

有两个选择。

### 方案 A：硬切换

直接移除 observation 的 Brave 路径：

- 删除或停止使用 `fetch_query_results()`。
- 删除 `observation/sources.py` 的 `search_web()`。
- 保留 `load_runtime_env()`。

优点：

- 架构更干净。
- 不维护两套 retrieval。

缺点：

- 没有 Agent backend 的用户无法跑 live observation。

### 方案 B：保留一版 fallback

保留旧 Brave 路径，但显式 opt-in：

```text
PMAGENT_OBSERVATION_BACKEND=brave
```

或者：

```text
pmagent observe run --backend brave
```

优点：

- 迁移更稳。
- 调试更容易。

缺点：

- 代码更复杂。
- 统一路径目标延后。

我的建议：

> 如果项目已经有人依赖 Brave observation，用方案 B 过渡一版；如果当前主要是本地快速迭代，可以方案 A，但必须先保证 Agent path 测试充分。

---

## 5. 文件级修改清单

### 5.1 新增文件

```text
src/pmagent/executors/__init__.py
src/pmagent/executors/_subprocess.py
src/pmagent/executors/_claude.py
src/pmagent/executors/_codex.py
src/pmagent/executors/_kiro.py
src/pmagent/executors/registry.py
src/pmagent/scaffold/config/executors.yaml
src/pmagent/skills/steps/run-observation/skill.md
tests/test_executors.py
tests/test_observation_agent.py
```

### 5.2 修改文件

```text
src/pmagent/debate/executors.py
src/pmagent/debate/config.py
src/pmagent/observation/runner.py
src/pmagent/observation/cli.py
src/pmagent/observation/executor.py
src/pmagent/observation/sources.py
src/pmagent/skills/README.md
src/pmagent/scaffold/AGENTS.md
src/pmagent/scaffold/config/agent-workflow.yaml
README.md
tests/test_init_upgrade.py
tests/test_observation_cli.py
tests/test_cli_subsystems.py
```

### 5.3 理论上不应大改的文件

```text
src/pmagent/observation/scheduler.py
src/pmagent/observation/status.py
src/pmagent/observation/cards.py
src/pmagent/observation/maintenance.py
```

如果这些文件需要大改，说明设计可能已经破坏当前 observation governance，需要重新审视。

---

## 6. 数据契约

### 6.1 run root

每次 observation run 应有：

```text
observations/<project>/runs/<run_id>/
  query-plan.json
  raw-findings.jsonl
  meta.json
  decisions.json
  summary-write-preview.md
```

### 6.2 canonical observation file

每条 finding 转成：

```text
observations/<project>/files/obs-<run_id>-NN.json
```

建议 schema：

```json
{
  "schema_version": 1,
  "id": "obs-20260424T010203Z-abcd1234-01",
  "project": "alpha",
  "created_at": "2026-04-24T01:02:03Z",
  "kind": "market",
  "title": "Competitor launched new workflow",
  "summary": "A concise summary of why this matters.",
  "source_url": "https://example.com/article",
  "evidence": [
    {
      "title": "Source title",
      "url": "https://example.com/article",
      "quote_or_summary": "Short grounded evidence summary."
    }
  ],
  "tags": ["market"],
  "run_id": "20260424T010203Z-abcd1234",
  "age": "2d",
  "query": "alpha market change",
  "confidence": "medium"
}
```

### 6.3 index 更新

```json
{
  "schema_version": 1,
  "project": "alpha",
  "observation_ids": [
    "obs-20260424T010203Z-abcd1234-01"
  ],
  "updated_at": "2026-04-24T01:02:03Z"
}
```

### 6.4 state 更新

```json
{
  "schema_version": 1,
  "project": "alpha",
  "enabled": true,
  "cadence": "daily",
  "last_run_id": "20260424T010203Z-abcd1234",
  "last_run_at": "2026-04-24T01:02:03Z",
  "next_scheduled_run_at": null,
  "observation_count": 1,
  "updated_at": "2026-04-24T01:02:03Z"
}
```

---

## 7. 风险与缓解

| 风险 | 原因 | 缓解 |
|---|---|---|
| headless Agent 没有真正执行 ingest | `observe run` 可能误报成功 | Agent 返回后检查 raw-findings/meta/decisions/state.last_run_id |
| 网页 prompt injection | Agent 会读取外部网页 | Agent 只写 raw findings，canonical mutation 由 ingest 完成 |
| CLI flags 版本差异 | Kiro/Codex/Claude headless 参数可能变 | backend wrapper 单独封装，mock argv 测试 |
| 移除 Brave 后用户不可用 | 有用户可能只有 Brave key，没有 Agent backend | 可保留一版 explicit fallback |
| inside-agent 输出被忽略 | stdout 不会自动触发 Agent 行为 | 输出明确人类可读步骤 + machine JSON |
| ingest 过早生成 candidate cards | 破坏 project observation / workspace review 边界 | ingest 只写 observations，不写 candidate-updates |
| 配置迁移破坏 debate | 现有用户依赖 debate-executors.yaml | 保留 debate-executors.yaml 优先级 |

---

## 8. 推荐实现顺序

建议按这个顺序做：

1. 补/确认当前 observation canonical behavior 测试。
2. 抽 `pmagent.executors`。
3. 加 Kiro backend。
4. 加 executor 测试。
5. 加可选 `executors.yaml`，但不删除 `debate-executors.yaml`。
6. 加 `pmagent observe plan`。
7. 加 `pmagent observe ingest`。
8. 加测试证明 ingest 写 project observations，不写 candidate cards。
9. 加 `run-observation` skill。
10. 改 `observe run` 为 inside-agent / headless delegation。
11. 加 completion verification。
12. 更新 README / scaffold / workflow docs。
13. 最后再决定是否删除旧 Brave observation 路径。

---

## 9. 验收标准

### 9.1 Executor 层

- `pmagent.executors` 存在。
- Debate 仍通过 compatibility wrapper 工作。
- Claude / Codex / Kiro 都有单测。
- backend 缺失时错误信息清晰。

### 9.2 Observation plan / ingest

- `pmagent observe plan --project <p> --json` 不需要 Brave key。
- `pmagent observe ingest --project <p> --run-id <id> --findings <path>` 能校验 JSONL。
- ingest 写 project-level observation files。
- ingest 更新 `index.json` 和 `state.json`。
- ingest 不直接创建 candidate cards。
- `pmagent observe review --workspace <w>` 能看到 ingest 后的 unread observations。

### 9.3 Agent-delegated run

- 在 Agent session 内，`observe run` 输出明确 handoff。
- 不在 Agent session 内，`observe run` 启动可用 backend。
- headless 执行后会验证 ingest 是否完成。
- 失败时有明确 metadata 和非 0 退出。

### 9.4 兼容性

- scheduler 命令形态不变。
- `debate-executors.yaml` 继续支持。
- README 不再错误声称 `observe run` 必须 Brave key。
- 如果 `pmagent search` / `digest` 仍使用 Brave，文档仍保留 Brave 说明。

---

## 10. 推荐测试矩阵

最小测试：

```bash
python -m pytest tests/test_executors.py -q
python -m pytest tests/test_observation_cli.py tests/test_observation_agent.py -q
python -m pytest tests/test_cli_subsystems.py tests/test_init_upgrade.py -q
```

合并前完整测试：

```bash
python -m pytest -q
```

手动 smoke test：

```bash
pmagent observe plan --project alpha --json
pmagent observe ingest --project alpha --run-id <run_id> --findings observations/alpha/runs/<run_id>/raw-findings.jsonl
pmagent observe review --workspace alpha-observe --json
pmagent observe run --project alpha
```

---

## 11. 需要记录的核心设计决策

建议在 PR 或 commit message 里明确写下：

> Observation ingest 保留 project-level canonical signal log，不直接生成 candidate cards。candidate cards 是 workspace review 工件，继续由 candidate-review 流程管理。

这是对 issue 原始方案最重要的修正。

---

## 12. 最终建议

建议按这个调整版实现 Issue #5：

```text
抽 shared executors：是
加 kiro 支持：是
Agent-delegated search：是
新增 observe plan：是
新增 observe ingest：是
ingest 直接生成 candidate cards：否
ingest 写 project-level observations：是
candidate-review 流程保持不变：是
```

这样既能获得 Agent 搜索质量提升，又不会破坏当前 observation / review / maintenance / PRD 的安全治理链路。
