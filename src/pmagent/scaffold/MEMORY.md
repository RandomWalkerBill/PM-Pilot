<!-- PMAGENT:VERSION:0.1.0 -->

<!-- PMAGENT:MANAGED:BEGIN -->
# 产品记忆索引（MEMORY）
> 定位：`MEMORY.md` 是全局“索引 / 摘要层”。长期可复用的细粒度结论沉淀到 `memory/`（原子化 notes + 显式链接网络）；项目级知识沉淀到 `projects/<project>/memory/`；需求级内容落在 `workspaces/<workspace>/`。

## 仓库架构

本仓库采用 **内核 + Project（项目）+ Workspace（需求）** 三层架构：

```text
pmagent/
├── AGENTS.md / MEMORY.md        # 全局入口
├── memory/                      # 全局记忆（persona + global）
├── context/                     # 全局上下文
├── decisions/                   # 全局决策（Agent 方法论级）
├── research/                    # 全局调研 + daily-digest
├── projects/                    # 项目级内容（长期积累）
└── workspaces/                  # 需求级工作空间（一个需求 = 一个目录）
```

## 内核与 CLI

- 模板：内嵌在各 step skill 文件中（PRD / Strategy / Decision / Research / Testcase）；Memory 与 Quality Log 模板见 `memory/EVOLUTION_ROUTINE.md`
- CLI：`pmagent`（当前共有 14 个一级子命令：init / upgrade / retrieve / search / link / conflicts / export / digest / weekly / workspace-init / switch / skills-sync / install-launchd / observe）
- 配置：`config/projects.json`（项目列表 + 激活项目 + 激活 workspace + 关键词路由）
- 工作流合同：`config/agent-workflow.yaml`（给外部 agent 的结构化执行链路）
- 隔离：`pmagent switch` 动态更新 `.vscode/settings.json` 的 `files.exclude`，切换时排除非活跃项目/需求
- 运维：`ops/`（quality-log / weekly-reports）和 launchd 模板

## 真相源层级

1. CLI / Python 行为
2. `config/agent-workflow.yaml`
3. `AGENTS.md`
4. 运行时状态文件（`projects.json`、`workspace-summary.md`、observation 状态）
5. docs（仅面向人）

## CLI 清单

- 查看完整命令：`pmagent --help`
- 初始化：`pmagent init --dir <data_dir>`
- 升级受管文件：`pmagent upgrade --data-dir <data_dir>`
- 仓库检索：`pmagent retrieve --query "<关键词>" --include-memory-index`
- 外部检索：`pmagent search --query "<关键词>"`
- 双向链接：`pmagent link --project <project> --file <path>`
- 冲突检测：`pmagent conflicts --all --threshold 0.4`
- Dev Pack 导出：`pmagent export --project <project> --workspace <workspace>`
- 日报：`pmagent digest`
- 周例行：`pmagent weekly`
- Workspace 初始化：`pmagent workspace-init --project <project> --workspace <workspace>`
- 项目切换：`pmagent switch <project> [workspace]`
- Skills 同步：`pmagent skills-sync --data-dir <data_dir>`
- 定时任务安装：`pmagent install-launchd daily-digest --hour 9 --minute 0`
- Observation：`pmagent observe run --project <project>`

## 工作约定（长期有效）

- 重要结论可追溯：项目级内容落 `projects/<project>/`，需求级内容落 `workspaces/<workspace>/`，全局方法论落根 `decisions/` 或 `memory/`
- 新信息进入后触发“记忆演化”：见 `memory/EVOLUTION_ROUTINE.md`
- PRD 必须链接上游 Strategy；若不一致，先回写 Strategy 再更新 PRD
- 决策必须追踪结果：`decisions/` 的“结果与复盘” 为必填，状态需持续更新
- Agent 质量监控：每周抽查 5 条输出，记录到 `ops/quality-log/`，见 `memory/EVOLUTION_ROUTINE.md`
- 定时自动化任务：
  - 日报监控：每天 09:00
  - 每周例行（冲突检测 + 质量监控模板）：每周一 09:30
  - 详见 `pmagent install-launchd --help`
- Dev Pack 导出：PRD 定稿后导出到 `workspaces/<workspace>/exports/vN/`（版本自动递增）
<!-- PMAGENT:MANAGED:END -->

<!-- 以下内容由用户维护，pmagent upgrade 不会修改 -->

## 快速入口

### 全局

- 长期记忆（Atomic Notes）：`memory/README.md`
  - Persona（稳定偏好 / 方法论）：`memory/persona/`
  - Global（跨项目通用知识）：`memory/global/`
- 全局上下文：`context/README.md`
- 全局调研：`research/`
- 全局决策：`decisions/`

### 项目层

（暂无项目）

### 需求工作空间

（暂无工作空间）

## 产品摘要（高层）

（暂无项目，内容已于 2026-03-19 清空重置）

## 关键原子记忆索引（精选）

### Persona（原则/方法）— 全局 `memory/persona/`

（暂无记忆条目）

## 关键决策索引

> 全局决策（Agent 方法论）写入根 `decisions/`；项目决策写入 `projects/<project>/decisions/`。

### 全局决策

（暂无决策）

## 术语表（简）

- PM：产品经理
- RD：研发工程师
- QA：测试工程师
- Requirement：需求
- Feature/Task：需求拆分后的可交付任务单元
- Dev Pack：PRD + 上下文的打包导出，供开发环境消费
