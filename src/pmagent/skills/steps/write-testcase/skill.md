# Skill: 写测试用例

## Description

**从 PRD 的功能与验收标准反推测试覆盖，明确主流程、边界条件和异常路径。**

## 触发条件

- PRD 完成后用户选择"生成测试用例"
- 用户主动要求补充测试用例

## 前置检查

1. 确认关联的 PRD 已存在且定稿。
2. 读取 PRD 中的功能清单（第 5 节）和验收标准。

## 执行步骤

### Step 1: 分析覆盖维度

从 PRD 的功能清单中提取：
- 主流程（Happy path）
- 边界条件
- 异常/错误态
- 非功能需求（性能、兼容性）

### Step 2: 写测试用例

按以下模板输出。要求：
- 至少 5 条用例
- P0 覆盖所有主流程
- P1 覆盖边界条件
- P2 覆盖异常态
- 每条用例的**预期结果**必须具体可验证

### Step 3: 落盘

- 写入 `workspaces/<workspace>/exports/vN/`（与同版本 PRD 在同一目录）
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确

## 模板真相源

- 测试用例的唯一模板真相源：`../../../templates/TESTCASE_TEMPLATE.md`
- 本 skill 不再内嵌模板正文；如模板结构变更，只修改 `templates/` 下对应文件

### 本 step 的额外约束

- 文件名建议：`YYYY-MM-DD-<feature-or-theme>-testcase.md`
- 至少 5 条用例
- P0 覆盖主流程，P1 覆盖边界条件，P2 覆盖异常态
- 每条用例的预期结果必须具体可验证



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
