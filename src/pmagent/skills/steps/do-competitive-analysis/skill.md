# Skill: 竞品分析

## Description

**围绕固定对比维度拆解竞品，给 strategy / PRD 提供更可落地的竞争判断。**

## 触发条件

- 用户要求做竞品分析 / 竞品对比
- 0-to-1 模式的 Research 阶段涉及竞品
- 写 Strategy 前需要了解竞争格局

## 与 do-research 的区别

- **do-research**：通用调研，回答开放性问题（技术可行性、用户行为、行业趋势）
- **do-competitive-analysis**：聚焦竞品对比，有固定的对比框架和输出结构

## 前置检查

1. 明确分析目标：是全景扫描还是深度拆解 2-3 个核心竞品？
2. 确认落盘位置：项目级 → `projects/<project>/research/`；需求级 → `workspaces/<workspace>/research/`。
3. 确认对比维度（用户指定或 Agent 建议）。

## 执行步骤

### Step 1: 确定竞品列表与对比维度

- 与用户确认竞品范围（直接竞品 + 间接竞品/替代方案）
- 确定对比维度，常用维度：
  - 核心功能覆盖
  - 目标用户 / 定位
  - 定价模型
  - 技术架构 / 平台
  - UX / 交互差异
  - 增长策略 / GTM
  - 优劣势总结

用户可增减维度。

### Step 2: 信息收集

- **外部**：执行 `pmagent search --query "<关键词>"`，每个竞品至少搜索 2 轮（产品名 + 核心关键词）
- **仓库内**：执行 `pmagent retrieve --query "<关键词>" --include-memory-index` 检索历史调研
- 区分"内部推理"与"外部引用"，外部引用标注来源链接
- 优先找：官方文档、产品更新日志、用户评价、行业分析报告

### Step 3: 写竞品分析报告

按以下模板输出。核心原则：
- **结构化对比**：用表格，不要用大段文字
- **So What**：每个发现都要回答"对我们意味着什么"
- **机会与威胁**：最终落到可行动的洞察

### Step 4: 落盘

- 写入对应 research 目录
- 如有决策性结论（如定位差异化方向），提示用户是否需要同步到 decisions/ 或 strategy/
- [ ] 检查是否有内容需同步到 project 层（提示用户确认）
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确

## 竞品分析模板

> 文件名：`YYYY-MM-DD-competitive-analysis-<topic>.md`

```markdown
# 竞品分析：[主题]

- **日期**：YYYY-MM-DD
- **分析目标**：[要回答什么问题]
- **竞品范围**：[列出所有分析的竞品]

## 竞品概览

| 竞品 | 一句话定位 | 目标用户 | 阶段/规模 |
|------|-----------|---------|----------|
| A    |           |         |          |
| B    |           |         |          |

## 功能对比矩阵

| 维度 | 我们 | 竞品 A | 竞品 B | 备注 |
|------|------|--------|--------|------|
|      |      |        |        |      |

## 逐竞品深度拆解

### 竞品 A：[名称]

- **核心卖点**：
- **优势**：
- **劣势/短板**：
- **定价**：
- **对我们的启示**：

### 竞品 B：[名称]

（同上结构）

## 竞争格局总结

### 行业共性（大家都在做的）

-

### 差异化机会（别人没做好 / 没做的）

-

### 威胁与风险

-

## 对我们的建议

| 建议 | 优先级 | 依据 |
|------|--------|------|
|      |        |      |

## 信息来源

| 来源 | 链接 | 获取日期 |
|------|------|----------|
|      |      |          |
```



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
