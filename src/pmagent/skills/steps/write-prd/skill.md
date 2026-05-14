# Skill: 写 PRD

## Description

**把已收敛的 requirement、research、strategy 和约束整理成 canonical PRD，并明确后续交接。**

## 触发条件

- 用户要求写 PRD / 落 PRD
- 0-to-1 或迭代模式流程推进到 PRD 阶段

## Step Contract（协议边界）

- **Reads**：`Requirement.md`、`workspace-summary.md`、strategy、research、context、decisions、当前对话。
- **Writes**：`prd/YYYY-MM-DD-<feature>-prd.md`，必要时更新 `prd/current.md`，并同步 `workspace-summary.md` 的 PRD 状态。
- **May mutate**：当前 workspace 的 `prd/`、`exports/`、`workspace-summary.md`。
- **Must not mutate**：未经用户确认的 project/global memory；observation candidate queue。
- **Required user confirmation**：风险与对策候选、第三方挑战后的修改、导出选项。
- **Handoff**：交给 observation/maintenance 前，必须明确 canonical PRD 路径、当前 scope、未决问题和后续观察重点。

## 前置检查

1. 确认 Strategy Brief 已存在（`projects/<project>/strategy/`）。如无，先提示用户走 write-strategy。
2. 确认 Requirement.md 已建立且链接到 Project。
3. 检索仓库上下文（`pmagent retrieve --query "<关键词>" --include-memory-index`），收集 research、context、strategy 中的信息。

## 执行步骤

### Step 1: 信息盘点

- 列出已有信息（来自 strategy、research、context、对话）
- 标出缺失维度（用户、场景、约束、指标、风险）
- 如有缺失，向用户逐条确认（一次 1 个问题）

### Step 2: 写 PRD

按以下模板结构输出。所有章节必须填写，信息不足的标注 `[待补充: 原因]`。

**注意**：第 8 节「风险与对策」先留空（标注 `[见 Step 3 候选确认]`），由 Step 3 单独处理。

### Step 3: 风险与对策候选确认

> **⛔ GATE: 候选确认制 — 此步骤不可跳过，不可与 Step 2/Step 4 合并。**
> 未完成此步骤前，禁止将风险写入 PRD 第 8 节。

**流程**：

1. AI 生成 3-5 条风险候选，每条包含：风险描述、影响、概率、建议对策、来源标注
   - 来源必须为以下之一：`Strategy 继承`（从 Strategy Brief 风险节延续）、`PRD 推导`（从本 PRD 功能/架构推导）、`外部参考`（来自检索/行业通识，附链接）
2. 以表格形式呈现候选列表，等待用户逐条确认
3. 用户对每条候选执行以下操作之一：
   - ✅ 采纳（原样或微调后采纳）
   - ❌ 拒绝（说明原因）
   - ✏️ 改写（用户提供修改版本）
4. 用户可补充 AI 未列出的风险
5. 仅将用户确认的风险写入 PRD 第 8 节

**禁止行为**：
- 不可在 Step 2 中预填第 8 节内容
- 不可将未经确认的风险写入最终 PRD
- 不可跳过此步骤直接进入挑战

### Step 4: 第三方挑战

按 **challenge-prd skill** 执行。

写完 PRD 后自动进入挑战流程：体验走查 → 逐视角挑战 → 输出挑战清单 → 用户确认是否修改。

### Step 5: 落盘

- 写入 `workspaces/<workspace>/prd/YYYY-MM-DD-<feature>-prd.md`
- 如该 PRD 成为当前主真相源，同步或提示维护 `workspaces/<workspace>/prd/current.md`
- 更新 `workspace-summary.md`：
  - `Current PRD`：是否存在、canonical path、当前 scope
  - `Current State`：`delivery` 或 `ready-for-development`
  - `Open Questions`：PRD 中仍未解决的问题
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确

### Step 6: 选项

PRD 定稿后，提供选项：

| 选项 | 产物 | 操作 |
|------|------|------|
| A. 改写压缩 | 人类可读的精简 PRD | 输出到 `exports/vN/` |
| B. 设计稿对齐 | 嵌入原型图的 PRD | 向用户索要原型图，对齐后输出到 `exports/vN/` |
| C. 测试用例 | 测试用例文档 | 调用 write-testcase skill，输出到 `exports/vN/` |
| D. 工程视角打分 | 工程可行性评分卡 | 调用 engineering-score skill，输出到 `exports/vN/` |
| E. 生成交互文件 | 页面清单 + 流程图 + 逐页交互描述 | 调用 gen-interaction skill，输出到 `exports/vN/interaction/` |

> **⛔ GATE: 选项必须完整呈现**
> 必须满足以下条件才能执行导出：
> - [ ] **A/B/C/D/E 所有选项全部展示**给用户（不可省略任何一个）
> - [ ] 用户已明确选择（可选 1 个或多个，也可全部不选）
> - [ ] 只执行用户选择的选项，不多不少
> 未通过此 Gate 不得开始导出。

用户选择后，调用 export-devpack skill 执行导出。

用户可选 1 个或多个。 


## 模板真相源

- PRD 的唯一模板真相源：`../../../templates/PRD_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名建议：`YYYY-MM-DD-<feature-or-theme>-prd.md`
- 第 8 节「风险与对策」在候选确认前必须保持空白或占位，不得提前写入未经确认的内容
- 与 Strategy 的一致性校验仍然属于必填要求
