# Skill: PRD-原型三文件同步

## Description

**保证 PRD、交互式 PRD 和 prototype 三个文件持续对齐，不让文档和原型互相漂移。**

## 触发条件

每次修改以下三个文件中的**任意一个**后，必须执行此 skill：

1. `PRD.md` — 源 PRD（Markdown）
2. `PRD-interactive.html` — 交互式 PRD 查看器（HTML，含 PRD 正文内容 + iframe 嵌套原型）
3. `prototype.html` — 原型图（HTML，独立运行）

**触发时机：** 不是"改完所有文件后统一检查"，而是**每次对任一文件做出实质性修改后立即执行**。

## 三文件关系

```
PRD.md（源头）
  ↕ 内容必须双向一致
PRD-interactive.html（呈现层，含 PRD 正文 + 原型 iframe）
  ↕ 交互描述 ↔ 原型实际页面
prototype.html（原型图，被 iframe 嵌入）
```

- `PRD.md` 和 `PRD-interactive.html` 的 PRD 正文内容必须表达一致（允许格式差异，不允许事实差异）
- `PRD-interactive.html` 的交互描述（S6 页面描述）必须和 `prototype.html` 的实际页面一一对应
- `prototype.html` 的页面命名、功能、数据必须和 PRD 需求清单匹配

## 必须对齐的维度

每次同步时逐条检查以下维度：

| # | 维度 | 检查内容 |
|---|------|---------|
| 1 | **核心范式** | 产品核心交互方式的描述是否三文件一致 |
| 2 | **需求清单** | 需求 ID、名称、验收标准是否三文件一致 |
| 3 | **页面结构** | 页面数量、命名、职责描述是否一致 |
| 4 | **用户旅程** | flow 步骤名称和顺序是否一致 |
| 5 | **里程碑** | 阶段划分和范围描述是否一致 |
| 6 | **成功指标** | 指标名称、口径、目标值是否一致 |
| 7 | **页面命名** | 导航按钮、标签、JS labels 是否和 PRD 页面命名一致 |
| 8 | **功能点** | 原型中实际存在的功能是否都在 PRD 中有对应描述 |

## 执行步骤

### Step 1: 识别变更源

确定本次修改的是哪个文件，以及修改了什么内容（新增功能？改名？删除功能？调整交互？）。

### Step 2: 读取另外两个文件的对应段落

不需要通读整个文件。根据变更内容，定位另外两个文件中**需要检查的具体段落**。

### Step 3: 逐维度比对

按上方 8 个维度检查是否有差异。只关注**事实性差异**，不纠结格式和措辞。

### Step 4: 列出差异并修复

如果发现差异：
- 向用户回显差异清单（一句话说明每处差异）
- 立即修复，不需要额外确认（因为同步是必须的）
- 修复后简要回显修改了哪些文件的哪些位置

如果无差异：一句话确认"三文件已对齐，无需修改"。

## 不做的事

- 不改设计风格（CSS/颜色/字体不在同步范围内）
- 不改业务逻辑（这不是 code review）
- 不补充新内容（同步 ≠ 扩写）
- 不做全文重写（只改差异点）


## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
