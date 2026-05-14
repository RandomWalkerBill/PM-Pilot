# Skill: 生成交互文件

## Description

**把 PRD 转成页面清单、流程图和逐页交互说明，供设计或原型阶段继续使用。**

## 触发条件

- PRD 定稿后用户选择选项 E
- 用户要求从 PRD 生成交互描述 / Figma 输入文件

## 前置检查

1. 确认 PRD 已落盘（`workspaces/<workspace>/prd/` 下存在对应文件）。
2. 检索 PRD 中第 3 节（用户与场景）、第 5 节（详细需求）、第 6 节（交互与体验）作为核心输入。
3. 如有历史交互文件（`exports/vN/interaction/`），读取作为参照。

## 输出物

交互文件写入 `exports/vN/interaction/YYYY-MM-DD-<feature>-interaction.md`，包含：

1. **页面清单**：从 PRD 功能列表推导出所有独立页面/视图
2. **每页交互描述**：结构化的交互规格，可直接导入 Figma 或作为设计师参考
3. **全局流程图**：Mermaid flowchart，串联所有页面的跳转关系

## 执行步骤

### Step 1: 提取页面清单

从 PRD 第 5 节（功能清单）和第 6 节（交互与体验）中提取所有页面/视图：

- 列出页面名称、对应的需求 ID（R1/R2/...）、页面类型（主页面/弹窗/底sheet/抽屉等）
- 以表格形式呈现，等用户确认：
  - 是否有遗漏页面
  - 是否有不需要的页面
  - 页面命名是否准确

> **⛔ GATE: 页面清单必须经用户确认后才能进入 Step 2。**

### Step 2: 全局流程图

用 Mermaid flowchart 描述页面间的跳转关系：

```
flowchart TD
    A[页面A] -->|操作| B[页面B]
    B -->|条件| C[页面C]
```

规则：
- 每个节点 = Step 1 确认的页面
- 每条边 = 用户操作或系统触发，标注触发条件
- 包含入口（从哪里进入）和出口（完成/取消/返回）
- 标注异常路径（网络错误、权限不足、数据为空等）

### Step 3: 逐页交互描述

对每个页面输出以下结构：

```markdown
## 页面：<页面名称>

**对应需求**: R1, R3
**页面类型**: 主页面 | 弹窗 | 底sheet | ...
**入口**: 从哪个页面/操作到达

### 布局区域

| 区域 | 内容 | 说明 |
|------|------|------|
| 顶部导航 | 返回按钮 + 标题 | ... |
| 主内容区 | ... | ... |
| 底部操作栏 | ... | ... |

### 交互行为

| 触发元素 | 用户操作 | 系统响应 | 目标状态/页面 |
|----------|----------|----------|--------------|
| 提交按钮 | 点击 | 校验表单 → 调用接口 → 跳转 | 成功页 |
| 返回按钮 | 点击 | 弹确认弹窗（有未保存内容时） | 上一页 |

### 状态变体

| 状态 | 触发条件 | 显示内容 |
|------|----------|----------|
| 空状态 | 列表数据为空 | 插画 + "暂无数据" + 引导操作 |
| 加载中 | 接口请求中 | 骨架屏 / spinner |
| 错误态 | 接口失败 | 错误提示 + 重试按钮 |
| 无权限 | 用户无访问权 | 提示文案 + 联系管理员 |
```

### Step 4: 落盘与 Figma 指引

1. 将完整交互文件写入 `exports/vN/interaction/YYYY-MM-DD-<feature>-interaction.md`
2. 在文件末尾附加 Figma 使用指引：

```markdown
## Figma 导入建议

1. **页面结构**: 按「页面清单」在 Figma 中创建对应 Frame
2. **流程图**: 将 Mermaid 流程图作为 FigJam 中的用户流参考
3. **交互标注**: 每页的「交互行为」表对应 Figma Prototype 的连线
4. **状态变体**: 每页的「状态变体」对应 Figma 的 Variants / Component Set
5. **设计系统**: 如项目有 Design Token，在 `context/` 中链接
```

## 注意事项

- 只描述**交互逻辑**，不涉及视觉设计（颜色/字号/间距由设计师决定）
- 状态变体至少覆盖：正常态、空状态、加载中、错误态
- 如 PRD 第 6 节信息不足，向用户逐条补充（一次 1 个问题）
- 交互文件和 PRD 保持需求 ID 对应关系，方便回溯   


## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
