# Skill: 写决策记录

## Description

**把关键产品或范围决策沉淀成可追溯记录，避免后续重复争论或方向漂移。**

## 触发条件

- 用户做出关键产品决策（方案选择、技术取舍、范围裁剪）
- 调研或 PRD 过程中产生了需要记录的决策
- 用户主动要求记录决策

## 前置检查

1. 确认决策层级：
   - 需求级（只影响当前需求的方案选择）→ `workspaces/<workspace>/decisions/`
   - 项目级（影响多个需求 / 项目方向）→ `projects/<project>/decisions/`
   - Agent 方法论级 → 根 `decisions/`
2. 确认是否有历史相关决策（`pmagent retrieve --query "<关键词>" --include-memory-index`），避免重复或矛盾。

## 执行步骤

### Step 1: 提炼决策要素

从对话中提取：
- 背景和约束
- 备选方案（至少 2 个）
- 每个方案的优缺点
- 最终选择和理由

如信息不全，向用户逐条确认。

### Step 2: 写决策记录

按以下模板输出。关键要求：
- **备选方案**至少 2 个，各有优缺点分析
- **"放弃了什么"**必须填写
- **复盘触发条件**必须定义

### Step 3: 落盘

- 写入对应 decisions 目录（需求级 / 项目级 / 全局，见前置检查）
- 执行 `pmagent conflicts --all --threshold <threshold>` 检查是否与现有决策矛盾
  - 发现冲突时：展示冲突对（含冲突类型与原因）→ 用户确认 → 删除旧决策
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 更新 `MEMORY.md` 索引（如果是重大决策）
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确
- 检查是否需要修改已有 Strategy / PRD

## 模板真相源

- 决策记录的唯一模板真相源：`../../../templates/DECISION_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名建议：`YYYY-MM-DD-<decision-title>.md`
- 备选方案至少 2 个
- “放弃了什么”必须填写
- “复盘触发条件”必须明确



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
