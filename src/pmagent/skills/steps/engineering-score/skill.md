# Skill: 工程视角打分

## Description

**从工程可行性和实现清晰度角度评估 PRD，判断工程侧接手时还会卡在哪。**

## 触发条件

- PRD 定稿后，用户选择选项 D（工程视角打分）
- 用户主动要求"帮我从工程角度评估一下这个 PRD"

## 前置检查

1. 确认 PRD 已定稿（`workspaces/<workspace>/prd/` 中有完整 PRD）。
2. 检索仓库上下文（`pmagent retrieve --query "<关键词>" --include-memory-index`），收集已有技术决策、架构约束、历史工程经验。

## 评估维度

核心问题：**工程师读完这份 PRD，还需要追问几轮才能开始规划？**

从以下 6 个维度对 PRD 进行工程友好度打分（每项 1-5 分）：

| 维度 | 评估要点 | 1 分（读完满脑子问号） | 5 分（读完就能开始规划） |
|------|---------|---------------------|----------------------|
| **需求清晰度** | 功能描述是否无歧义，工程师能否准确理解"要做什么" | 大段模糊描述，读完不知道该做啥 | 每条需求指向明确行为，无需反复确认 |
| **边界定义** | 做什么 vs 不做什么是否说清楚 | 范围发散，没说清楚哪些先做哪些不做 | 明确写了这一期做什么、不做什么，以及为什么不做 |
| **场景完整性** | 用户遇到意外情况时怎么办，是否有交代 | 只描述了一切顺利的理想路径 | 主流程 + 用户出错/网络异常/数据缺失等常见意外都有说明 |
| **现实可行性** | PRD 有没有提出"不可能的需求"或忽视明显的限制 | 拍脑袋要求（如"0 延迟""100% 准确率"），脱离现实 | 需求合理，没有违反常识的预期 |
| **怎么算做完** | 成功标准是否写清楚，什么状态算"这个功能 OK 了" | "体验要好""速度要快"等主观描述 | 有具体的、可判定的完成标准（数字指标或明确状态） |
| **模块独立性** | 功能之间是否相对独立，还是全部纠缠在一起 | 功能相互依赖、牵一发动全身，无法分头推进 | 各模块边界清晰，可以独立理解和推进 |

## 执行步骤

### Step 1: 逐维度评估

对每个维度：
1. 从 PRD 中提取相关内容（引用具体章节和条目）
2. 给出分数（1-5）+ 一句话理由
3. 如信息不足无法评估，标注 `[信息不足: 需要补充 XXX]` 而非猜测打分

### Step 2: 输出评分卡

```markdown
## 工程视角评分卡

> PRD：[链接到 PRD 文件]
> 评估日期：YYYY-MM-DD

| 维度 | 分数 | 理由 | 依据（PRD 章节） |
|------|------|------|-----------------|
| 需求清晰度 | X/5 | ... | 第 X 节 |
| 边界定义 | X/5 | ... | 第 X 节 |
| 场景完整性 | X/5 | ... | 第 X 节 |
| 现实可行性 | X/5 | ... | 第 X 节 |
| 怎么算做完 | X/5 | ... | 第 X 节 |
| 模块独立性 | X/5 | ... | 第 X 节 |

**综合分：X/30**

### 阻塞项（分数 ≤ 2 的维度）

| 维度 | 问题 | 建议行动 |
|------|------|---------|
| ... | ... | ... |

### 改进建议（分数 3 的维度）

| 维度 | 可优化点 | 建议 |
|------|---------|------|
| ... | ... | ... |
```

### Step 3: 用户确认

- 展示评分卡，逐条与用户对齐
- 用户可调整分数或补充信息
- 如有阻塞项（≤ 2 分），提示用户是否需要回去修改 PRD

### Step 4: 落盘

- 写入 `workspaces/<workspace>/exports/vN/YYYY-MM-DD-engineering-score.md`（与 PRD 同一个 export 版本目录）
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
