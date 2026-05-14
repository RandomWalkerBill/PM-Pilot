# Skill: 导出 Dev Pack

## Description

**把当前 workspace 的核心产物整理成下游工程或交付方可直接消费的导出包。**

## 触发条件

- PRD 定稿或经过重大更新
- 用户选择"PRD 完成后的 3 选项"中的任意一项
- 用户主动要求导出
- 0-to-1 / 迭代模式的最后阶段

## 前置检查

1. 确认当前 workspace 有 PRD（`workspaces/<workspace>/prd/` 非空）。
2. 确认版本号：扫描 `exports/` 下已有的 `vN/` 目录，自动递增。
3. 确认用户需要哪些产物（可多选）：
   - A. 改写压缩（精简版 PRD，适合人阅读）
   - B. 设计稿对齐（原型图链接/图片嵌入后的 PRD）
   - C. 测试用例（按 write-testcase skill 执行）

> **⛔ GATE: 选项来源校验**
> 执行导出前必须确认：
> - [ ] 用户的选择是基于完整的 A/B/C 三选项呈现后做出的（不是 Agent 自行缩减后的选项）
> - [ ] 如未呈现完整选项，先补呈现再执行
> 未通过此 Gate 不得开始导出。

## 执行步骤

### Step 1: 备份当前 PRD

- 将 `prd/` 中的当前版本完整复制到 `exports/vN/`
- 这是**版本保护的强制步骤**——无 Git 环境下，覆盖即消失

### Step 2: 生成附加产物（按用户选择）

#### 选项 A: 改写压缩

- 从完整 PRD 提炼核心内容
- 移除内部讨论痕迹、假设标注、Agent 批注
- 保留：目标、范围、用户故事、核心流程、里程碑
- 输出到 `exports/vN/PRD-compact.md`

#### 选项 B: 设计稿对齐

- 在 PRD 中嵌入原型图链接或截图引用
- 标注每个页面/流程对应 PRD 的哪个章节
- 输出到 `exports/vN/PRD-with-design.md`

#### 选项 C: 测试用例

- 按 write-testcase skill 执行
- 输出到 `exports/vN/testcases.md`

### Step 3: 生成 Dev Pack 索引

在 `exports/vN/` 下创建 `README.md`，列出本次导出的所有文件及版本信息。

### Step 4: 落盘确认

- 回显完整路径和文件清单
- 如有项目级影响（如 Strategy 变更），提示用户确认是否同步到 project 层
- [ ] 检查是否有通用认知需落到全局 memory
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显目标路径，确认落地位置正确

## Dev Pack 索引模板

> 文件名固定为 `exports/vN/README.md`

```markdown
# Dev Pack vN

- **需求**：[Requirement.md](../../Requirement.md)
- **导出日期**：YYYY-MM-DD
- **导出者**：PM Agent

## 包含文件

| 文件 | 说明 |
|------|------|
| PRD.md | 完整版 PRD |
| PRD-compact.md | 精简版（如有） |
| PRD-with-design.md | 设计稿对齐版（如有） |
| testcases.md | 测试用例（如有） |

## 变更摘要

> 相比上一版本的主要变更：
```



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
