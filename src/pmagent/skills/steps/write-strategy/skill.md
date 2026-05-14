# Skill: 写 Strategy Brief

## Description

**把调研与上下文提炼成方向性判断，作为 PRD 之前的价值层与边界层锚点。**

## 触发条件

- 0-to-1 模式推进到 Strategy 阶段
- 用户要求写产品方向 / 战略文档
- 新项目冷启动，需先定方向再写 PRD

## 前置检查

1. 确认 Project 已存在。如无，先新建 `projects/<project>/`。
2. 确认落盘层级：
   - 项目整体方向 → `projects/<project>/strategy/`
   - 只影响当前需求（大需求）→ `workspaces/<workspace>/strategy/`
3. 执行 `pmagent retrieve --query "<关键词>" --include-memory-index` 检索已有 research、strategy、context、decisions。
4. 执行 `pmagent search --query "<关键词>"` 补充外部信息（行业趋势、竞品动态）。

## 执行步骤

### Step 1: 信息收集

- 执行 `pmagent retrieve --query "<关键词>" --include-memory-index` 盘点已有 research、context、历史 strategy
- 执行 `pmagent search --query "<关键词>"` 外部检索补充（标注来源）
- 与用户对齐核心问题：做什么、不做什么、成功长什么样

### Step 2: 指标与风险候选确认

> **⛔ GATE: 候选确认制 — 此步骤不可跳过，不可与 Step 3 合并。**
> 未完成此步骤前，禁止输出 Strategy Brief 正文。

**指标候选（第 4 节）：**

1. AI 基于 Step 1 收集到的 research/context/对话信息，生成 3-5 个「成功指标」候选项
2. 每条候选标注推导依据（引用来源文件路径或对话内容）
3. 以清单形式呈现给用户：

```
我基于已有信息整理了以下候选成功指标，请逐条确认：

- [ ] 候选 1: [指标描述]（依据：[来源]）
- [ ] 候选 2: [指标描述]（依据：[来源]）
- [ ] 候选 3: [指标描述]（依据：[来源]）

请操作：✅ 选中 / ✏️ 修改后选中 / ➕ 自行补充 / ❌ 全不要
```

4. 等待用户回复，根据用户选择整理最终指标

**风险候选（第 7 节）：**

5. 同样生成 3-5 个「风险」候选项，标注推导依据
6. 以相同清单形式呈现给用户，等待确认

**结果处理：**
- 用户 ✅ 选中 → 写入正文区
- 用户 ✏️ 修改 → 用修改后的版本写入正文区
- 用户 ➕ 补充 → 补充内容写入正文区
- 用户 ❌ 全不要 → 正文区写 `[暂无，后续补充]`
- **禁止将未经用户确认的候选项写入正文区**

### Step 3: 写 Strategy Brief

按以下模板结构输出。关键取舍至少 2 条，假设至少 1 条。
第 4 节和第 7 节仅填入 Step 2 中用户确认过的内容。

### Step 4: 落盘

- 写入目标目录（前置检查确定的层级）：
  - 项目级：`projects/<project>/strategy/YYYY-MM-DD-<topic>-strategy.md`
  - 需求级：`workspaces/<workspace>/strategy/YYYY-MM-DD-<topic>-strategy.md`
- 旧版本标记 `superseded`，不覆盖
- [ ] 检查是否有内容需同步到 project 层（需求级 strategy 可能需要）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确
- [ ] ⛔ 确认第 4 节正文区所有条目均经用户确认（非 AI 单方面填入）
- [ ] ⛔ 确认第 7 节正文区所有条目均经用户确认（非 AI 单方面填入）

## 模板真相源

- Strategy Brief 的唯一模板真相源：`../../../templates/STRATEGY_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名建议：`YYYY-MM-DD-<topic>-strategy.md`
- 第 4 节（成功指标）与第 7 节（风险与对策）仍然遵守候选确认制
- 这两个 section 在用户确认前，不得写入未经确认的正文内容




## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
