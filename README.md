# pmagent

`pmagent` 是一个嵌入外部 Agent 的 Python CLI 辅助层。它服务于 Claude Code、Codex 这类对话式 Agent，把长期项目知识、当前 workspace 状态、外部信号观察和交付导出统一落到可恢复、可审计的文件协议里。

它不是独立的 PM 软件，也不是单纯的文档模板仓库。更准确地说，它是一个给外部 Agent 使用的辅助工作流和长期项目知识库。

## 它能做什么

- 用 `project` / `workspace` 双层模型沉淀长期项目知识和当前需求上下文
- 给外部 Agent 提供 `status / route / review / start / next / resume` 这类稳定前门命令
- 把澄清、研究、PRD、maintenance 这些步骤变成可持续恢复的状态流
- 用 project 级 observation 持续发现外部变化，并在 workspace 侧显式 review / maintenance
- 把当前 workspace 导出成面向研发消费的 Dev Pack

## 适合什么场景

- 你想给 Claude Code / Codex 这类外部 Agent 配一个长期可用的项目知识库
- 你想把 PM 工作流从“聊天记录”变成可落盘、可恢复的文件协议
- 你需要持续跟踪外部变化，但又不希望自动化直接改写 PRD
- 你希望 Agent 在多轮协作里始终知道当前项目状态、当前阶段和下一步

## 安装

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
pmagent --help
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\pmagent.exe --help
```

如果当前 PowerShell 禁止执行脚本，可以临时放开当前进程：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pmagent --help
```

## 3 分钟接入 Agent 工作流

`pmagent` 更适合嵌入 Claude Code / Codex 这类外部 Agent 的工作流程，而不是当成一个需要你手工频繁敲命令的独立工具。

### 1. 先初始化一次数据目录

```bash
pmagent init --dir ~/pm-data
```

这一步只需要做一次。它会准备好项目知识库、workspace 结构、skills、templates 和运行时配置。

初始化会同时生成两个配置文件：

- `.env.example`：可提交的配置样例，用来给团队同步需要哪些环境变量。
- `.env`：本机私密配置文件，只在目标目录缺失时自动创建；已有 `.env` 会被保留，不会覆盖密钥。

`.env` 会从 `.env.example` 派生生成，安装包和源码仓库不需要携带 `scaffold/.env`。如果你之前遇到过类似 `FileNotFoundError: .../scaffold/.env` 的初始化错误，更新到包含该修复的版本后重新执行 `pmagent init --dir ~/pm-data` 即可。

### 2. 在 Agent 会话里让它接管当前项目上下文

你可以直接在 Claude Code / Codex 里打开data目录 输入下述内容：

```text
我想要做一个alpha项目, 用来......
```

底层通常会走：

```bash
pmagent start \
  --data-dir ~/pm-data \
  --project alpha \
  --workspace alpha-observe \
  --requirement-summary "Track market changes for alpha."
```

### 3. 后续让 Agent 围绕前门命令持续推进

一旦 workspace 建好，Agent 后续主要围绕这些命令工作：

```bash
pmagent status
pmagent review
pmagent next
```

也就是说，典型用法不是你自己手动记整套 CLI，而是让外部 Agent：

- 用 `status` 理解当前状态
- 用 `review` 进入当前最合适的工作面
- 用 `next` 决定下一步

如果你想显式建 workspace，也可以先手动执行：

```bash
pmagent workspace-init --data-dir ~/pm-data --project alpha --workspace alpha-observe
```

## 常用命令

### 前门命令

```bash
pmagent status
pmagent route
pmagent review
pmagent start
pmagent next
pmagent resume
```

### 阶段命令

```bash
pmagent clarify status
pmagent research status
pmagent prd status
pmagent prd init-draft
```

### observation 与导出

```bash
pmagent observe run --project <project>
pmagent observe plan --project <project> --json
pmagent observe ingest --project <project> --run-id <run_id> --findings <path>
pmagent observe review --workspace <workspace>
pmagent export --project <project> --workspace <workspace>
```

## 常见环境变量

- `PMAGENT_DATA_DIR`：覆盖默认数据目录
- `BRAVE_SEARCH_API_KEY`：`search`、`digest` 等直接搜索命令需要；`observe run` 默认委托外部 Agent 执行检索
- `PMAGENT_AGENT_BACKEND`：Observation 委托执行器，可设为 `kiro` / `kiro-cli` / `claude` / `codex`，默认自动探测
- `OPENAI_API_KEY`：部分 retrieval / linking / planning 能力可用
- `OPENROUTER_API_KEY`：可替代部分 OpenAI 调用

`pmagent init` 会在数据目录下生成 `.env` 和可提交的 `.env.example`；`pmagent upgrade` 会刷新 `.env.example`，但不会覆盖本机私密 `.env`。正常使用时只需要编辑数据目录里的 `.env`，不要在源码目录或 scaffold 目录里维护真实密钥。

## 进一步阅读

- [运行时数据目录说明](src/pmagent/scaffold/README.md)
- [Skills 地图](src/pmagent/skills/README.md)

