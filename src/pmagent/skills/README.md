# PM Agent Skills 地图

`skills/` 只描述可执行工作合同。运行时不再由 mode 锁定，`pmagent status/route/next/review` 会根据 artifact、readiness、inbox 和 `recommended_skills` 给出导航建议。

## Agent 推荐阅读顺序

1. `AGENTS.md`
2. `config/agent-workflow.yaml`
3. `config/projects.json`
4. `workspaces/<workspace>/.pmagent/current-state.json`
5. 需要执行具体 artifact 工作时再读 `skills/steps/<step>/skill.md`

## Step Skills

| Step | 路径 | 作用 |
| --- | --- | --- |
| Write Requirement | `steps/write-requirement/skill.md` | 产出或更新 Requirement / Workspace 共识 |
| Do Research | `steps/do-research/skill.md` | 通用调研 |
| Do Competitive Analysis | `steps/do-competitive-analysis/skill.md` | 竞品调研 |
| Write Strategy | `steps/write-strategy/skill.md` | 产出 strategy brief |
| Write PRD | `steps/write-prd/skill.md` | 产出 canonical PRD |
| Challenge PRD | `steps/challenge-prd/skill.md` | 多视角挑战 PRD |
| Write Decision | `steps/write-decision/skill.md` | 记录决策 |
| Write Testcase | `steps/write-testcase/skill.md` | 从 PRD 推导测试用例 |
| Export DevPack | `steps/export-devpack/skill.md` | 导出交付包 |
| Dev Readiness | `steps/dev-readiness/skill.md` | 把 PRD 转成 dev-plan 和 vertical slices |
| Dev Run Record | `steps/dev-run-record/skill.md` | 记录 slice run evidence 和 lesson candidates |
| Candidate Review | `steps/candidate-review/skill.md` | 审核远端建议和候选经验 |
| Run Observation | `steps/run-observation/skill.md` | Observation 检索和 ingest 协议 |

## 主链路

```text
pmagent init --dir <pm-data>
-> pmagent workspace-init
-> pmagent status / route / next / review
-> clarify / research / prd
-> external Agent executes skills/steps/dev-readiness/skill.md
-> pmagent dev slices
-> pmagent dev run-record
-> pmagent infra protocol
-> pmagent infra pull-cards
-> pmagent infra review-card
```

## 边界

- `recommended_skills` 是导航建议，不是锁定状态。
- `candidate-review` 是 review surface，不是 mode。
- `observation` 和 `infra` 不直接修改 canonical Markdown 正文。
- PM Data 保存 PM / dev 协议和证据；源码仍在外部 GitHub codebase。
