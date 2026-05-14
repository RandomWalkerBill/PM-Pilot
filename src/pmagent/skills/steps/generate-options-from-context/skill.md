# Skill: 基于问题定义生成方案

## Description

**基于已澄清的问题空间生成多个可比较方案，并解释为什么选这个、不选那个。**

## 触发条件

- 已经有结构化的问题定义，需要基于它生成方案
- 用户希望 Agent 提出多个方向、给出最优建议，并说明为什么不选其他方向
- 已完成问题空间澄清，希望进入解空间发散与收敛

## 前置条件

输入中至少应包含以下字段：

- `问题定义`
- `事实`
- `约束`
- `边界`
- `成功标准`

如果输入缺少以上关键部分，先回退到 `solve-from-context`，不要硬生成方案。

在正式生成方案前，默认先调用 `do-research` skill，围绕当前问题定义做一轮外部检索与归纳，补充：

- 行业最佳实践
- 竞品做法
- 相似问题的常见解法
- 明显的约束、风险、失败案例

只有在以下情况才可跳过：

- 问题是纯内部流程，外部世界几乎没有可参考对象
- 用户明确要求仅基于已提供上下文生成方案
- 当前输入已经包含足够新的外部研究材料

如跳过，必须明确说明跳过原因。

`generate-options-from-context` 不直接承担完整研究职责；默认输入应包含 `do-research` 的关键结论，或等价的外部发现摘要。

## 核心原则

- **先发散，后收敛**：先生成多个方向，再选择推荐方案。
- **先做外部校准，再做内部发散**：先看外部世界怎么做，再决定方案空间。
- **推荐不能直接继承用户倾向**：用户倾向只能作为参考，不能自动成为推荐结果。
- **必须有 rejected directions**：不仅说推荐什么，也要说为什么不推荐其他方向。
- **方案要回应根因**：每个方向都要明确它解决的是哪个问题，而不是只描述表层形式。
- **保留可修正性**：推荐结论必须绑定前提，前提变化时结论可变。

## 执行步骤

### Step 1: 校验输入

先检查输入是否足以支撑方案生成：

- 目标是否明确
- 成功标准是否明确
- 约束和边界是否明确
- 事实是否足够支撑判断

如果不够，列出最小缺口，不要直接补脑完成。

### Step 2: 调用 `do-research`

在生成方案前，默认先调用 `do-research`，围绕当前问题定义检索：

- 已有成熟做法
- 竞品或替代方案
- 行业内常见失败模式
- 最新工具、趋势、约束变化

检索输出至少整理为：

```markdown
## 外部发现
- 发现 1：
- 来源：
- 对当前问题的影响：
```

要求：

- `do-research` 的输出用于扩展和校准方案空间，不是拿来替代问题定义
- 外部发现与当前问题无关时，不要硬套
- 如外部信息与用户上下文冲突，必须显式指出冲突点

### Step 3: 提炼解题抓手

基于输入，先总结：

- 最关键的矛盾是什么
- 最值得优先解决的根因是什么
- 哪些约束会直接改变方案优先级

这一段用于约束后续发散，避免方案看起来很多，实则都没打中核心问题。

### Step 4: 发散候选方向

至少生成 2-4 个明显不同的方向。每个方向都要包含：

- 它解决的是哪个根因
- 它成立依赖什么前提
- 它的主要收益
- 它的主要代价
- 它的核心风险
- 它最适合什么场景

要求：

- 方向之间必须有真实差异，不能只是同一方案的轻微变体
- 至少有一个方向应明显不同于用户直觉或用户倾向

### Step 5: 选择最优方向

在候选方向基础上，给出当前最推荐的方向，并说明：

- 为什么它最符合当前事实、约束和成功标准
- 它相对其他方向赢在哪里
- 它牺牲了什么
- 哪些判断是基于事实，哪些是基于推断

### Step 6: 写明 rejected directions

对未被选择的方向逐一写明：

- 为什么没有被选中
- 是时机不对、约束不符、风险过高，还是收益不足
- 在什么条件变化后，它可能重新变成更优解

### Step 7: 以决策格式输出

默认按以下结构输出：

```markdown
## 输入摘要
- 核心目标：
- 关键约束：
- 成功标准：

## 外部发现
- 发现 1：
- 来源：
- 对方案设计的影响：

## 候选方向
### 方向 A
- 解决根因：
- 适用前提：
- 主要收益：
- 主要代价：
- 核心风险：

### 方向 B
...

## 最优建议
- 推荐方向：
- 推荐理由：
- 主要取舍：

## Rejected Directions
- 不选方向 A 的原因：
- 不选方向 B 的原因：

## 假设与待验证项
- 假设 1：
- 验证方式：
```

## 质量检查

- 我是否真的先调用了 `do-research` 或有充分理由跳过？
- 外部发现是否真的影响了方案空间，而不是只被我贴在答案里充数？
- 我是否真的给了 2-4 个不同方向，而不是一个方案的多个包装？
- 推荐方案是否只是沿用了用户倾向？
- 每个方向是否都回应了问题根因？
- 我是否明确写出了不选其他方向的原因？
- 推荐是否绑定了假设和适用前提？

## 常见失误

- 没有先调用 `do-research`，就直接开始出方案
- 外部检索只罗列信息，没有进入方案判断
- 只有推荐，没有对照项
- 方向之间差异太小，无法形成真实决策
- 把用户偏好直接包装成最优建议
- 只写优点，不写代价和风险
- 不写 rejected directions，导致结论不可审计



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
