# Skill: 做调研

## Description

**围绕关键问题补齐证据、风险与判断基础，把 workspace 推进到更稳的 readiness 状态。**

## 触发条件

- 0-to-1 模式推进到 Research 阶段
- 用户要求竞品分析、方案调研、用户调研
- 写 Strategy/PRD 前发现信息不足

## Step Contract（协议边界）

- **Reads**：`Requirement.md`、`workspace-summary.md`、已有 `research/`、`context/`、`decisions/`、必要时全局/项目级 memory。
- **Writes**：新的 research 报告；必要时写入 `decisions/`；更新 `workspace-summary.md` 的当前理解、关键结论、开放问题、重要链接。
- **May mutate**：当前 workspace 的 `workspace-summary.md` 与 research 目录。
- **Must not mutate**：PRD 正文；无关 project/workspace 的历史 research。
- **Required user confirmation**：调研范围、关键结论是否进入 decisions、是否同步到 project/global memory。
- **Handoff**：交给 Strategy/PRD 前，必须说明课题是否成立、证据在哪里、仍有哪些风险/开放问题。

## 前置检查

1. 明确调研目标和关键问题（用户确认或从上下文推断）。
2. 确认落盘位置：项目级 → `projects/<project>/research/`；需求级 → `workspaces/<workspace>/research/`。

## 执行步骤

### Step 1: 定义调研范围

- 与用户确认：要回答什么问题？
- 确定方法（外部检索 / 仓库检索 / 两者结合）
- 确定范围边界（包含什么、不包含什么）

### Step 2: 信息收集

- **仓库内**：执行 `pmagent retrieve --query "<关键词>" --include-memory-index` 检索历史
- **外部**：执行 `pmagent search --query "<关键词>"` 搜索（至少 2 轮，不同关键词）
- 区分"内部推理"与"外部引用"，外部引用标注来源链接

### Step 3: 写调研报告

按以下模板结构输出。核心原则：**结论 → 证据 → 含义**，避免堆链接。

### Step 4: 落盘

- 写入对应 research 目录
- 如有决策性结论，提示用户是否需要同步到 decisions/
- 更新 `workspace-summary.md`：
  - `Current Understanding`：只写当前仍有效的调研结论，不复制全文
  - `Key Decisions`：链接到对应 decision 文件
  - `Open Questions`：记录仍需继续观察或验证的问题
  - `Important Links`：链接本次 research 报告
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确

## 模板真相源

- Research 报告的唯一模板真相源：`../../../templates/RESEARCH_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名建议：`YYYY-MM-DD-<topic>-research.md`
- 报告结构必须遵循“结论 → 证据 → 含义”
- 重点不是堆链接，而是把外部发现转成可决策信息
