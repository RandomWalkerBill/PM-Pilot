# 飞书能否替代 PMAgent 服务器层：可行性与风险分析

调研日期：2026-04-29

> 2026-04-30 修订提示：本文是“飞书能否替代服务器层”的背景分析，不是当前最新落地方案。当前 V1 已进一步收敛为：暂不做服务器侧看板层；飞书优先作为文件协作层，保存主流程和 dev 的全部文件镜像；飞书表格只做机器索引、同步账本、建议和反馈记录；代码层在 GitHub；分析 Agent 读取飞书文件层并输出映射到主流程或 dev 位置的建议。最新方案见 `pmagent-feishu-file-layer-dev-doc-design.md` 和 `pmagent-current-feishu-claw-dev-slice-plan.md`。

## 1. 一句话结论

飞书可以作为 PMAgent 服务器层的协作型 backend，但不建议把飞书直接等同于 PMAgent 的完整服务器层。

更准确的结论是：

```text
可以用飞书替代服务器层里的“看板、协作、通知、建议卡片展示、部分同步快照存储”。

不建议用飞书替代服务器层里的“协议服务器、事件 ACK、冲突处理、权威快照、Agent 分析调度、本地状态一致性控制”。
```

所以推荐方向不是：

```text
PMAgent Server = 飞书
```

而是：

```text
PMAgent Server Backend = FeishuBackend
```

也就是说，PMAgent 内部仍保留自己的同步协议、outbox、inbox、状态机和冲突策略；飞书只是其中一个可插拔的远端 backend，用来承载项目看板、文档镜像、消息通知和建议反馈。

## 2. 为什么这个问题容易误判

从产品体验上看，飞书很像一个现成服务器：

- 飞书 Docs 可以放 Requirement / PRD / decisions；
- 飞书 Base 可以做项目看板、需求表、suggestion 表；
- 飞书 IM 可以推送通知和卡片；
- 飞书 Wiki 可以组织知识库；
- 飞书 CLI 可以让 Agent 读写飞书内容；
- 飞书自带权限、评论、协作和历史记录。

所以直觉上会觉得：

```text
那我还要自己写服务器干嘛？直接把服务器层改成飞书不就行了？
```

这个判断只对了一半。

飞书确实能省掉大量“协作界面”和“团队可见性”工作，但 PMAgent 文档里的服务器层并不只是一个界面。它还是 PMAgent 文件协议和状态协议的远端镜像、事件接收器、建议生成器、反馈收集器和冲突边界。

飞书擅长做协作平台，不擅长做 PMAgent 的协议内核。

## 3. PMAgent 服务器层到底是什么

根据 `pmagent-three-layer-product-model.md` 和 `pmagent-three-layer-implementation-guide.md`，服务器层有五个核心职责：

1. 接收本地主流程同步上来的 artifact / event；
2. 展示项目、需求、PRD、dev 状态看板；
3. 服务端 Agent 读取同步快照并生成 suggestion；
4. 将 suggestion 下发为本地 inbox item；
5. 收集 suggestion 的 accepted / ignored / deferred feedback。

第一版明确不做：

- 自动改本地 PRD；
- 自动替用户执行 research / debate / observation；
- 自动 fine-tune；
- 自动根据采纳率改 prompt。

这意味着服务器层的核心边界是：

```text
服务器是 mirror/advisory，不是本地 canonical artifact 的替代品。
```

本地文件仍然是权威来源：

```text
local canonical wins
server is mirror/advisory
```

这个原则非常关键。如果换成飞书后丢掉这个原则，系统会很快变成“双主写入”：

```text
本地 PRD 可以改
飞书 PRD 也可以改
Agent 可以改
人也可以改
同步器还要判断谁覆盖谁
```

这就是最大的复杂度来源。

## 4. 飞书能很好替代的部分

### 4.1 看板层

飞书 Base 很适合承载 PMAgent 的看板层。

可以用 Base 建这些表：

| 表 | 用途 |
|---|---|
| Projects | 项目列表 |
| Workspaces | workspace / requirement 工作区 |
| Artifacts | Requirement、PRD、research、decisions、dev-plan、slices 的索引 |
| Events | 本地同步事件日志 |
| Suggestions | 服务端建议卡片 |
| Feedback | accept / ignore / defer 反馈 |
| Dev Status | slice、blocked reason、QA、TDD 状态 |

Base 的视图、筛选、分组、仪表盘可以直接回答：

- 当前有哪些项目？
- 哪些需求还在澄清？
- 哪些 PRD 已生成？
- 哪些 PRD 进入 dev readiness？
- 哪些 slice 正在开发？
- 哪些 suggestion 待处理？
- 哪些开发反馈需要回流 PRD？

这部分用飞书非常合适。

### 4.2 文档镜像层

飞书 Docs / Wiki 适合展示和协作阅读：

- Requirement；
- PRD；
- decisions；
- research summary；
- debate synthesis；
- dev-plan；
- slice plan；
- release note。

但这里建议使用“镜像”语义，而不是“权威源”语义：

```text
本地 markdown 是 canonical。
飞书文档是 readable mirror。
```

原因是本地文件更适合作为 Agent 工作协议：

- 可版本化；
- 可 diff；
- 可测试；
- 可被 hooks 保护；
- 可被 Codex / Claude Code 直接读取；
- 可放进 dev handoff；
- 可在没有网络时工作。

飞书 Docs 更适合作为人类协作界面。

### 4.3 通知层

飞书 IM 很适合做：

- 同步成功通知；
- PRD 更新通知；
- suggestion 提醒；
- dev blocked 提醒；
- 每日/每周项目状态摘要；
- 需要人工决策的消息卡片。

这部分比自建通知系统更划算。

### 4.4 Suggestion 展示和反馈层

飞书可以很好地展示 suggestion card：

```json
{
  "suggestion_id": "sug-001",
  "kind": "research",
  "title": "建议补充竞品调研",
  "reason": "PRD 中存在未经证据支持的市场判断。",
  "recommended_skill": "research",
  "status": "pending"
}
```

在飞书中可以表现为：

- Base 的一条记录；
- 群里的消息卡片；
- 文档评论；
- 待办任务。

用户点击接受、忽略、暂缓后，可以写回 Base 的 status 字段，然后 PMAgent 本地 pull 时同步成 inbox 状态。

这部分可行性也很高。

## 5. 飞书不适合直接替代的部分

### 5.1 事件 ACK 和 outbox 协议

PMAgent 实现文档里设计了本地 outbox：

```text
workspaces/<workspace>/.pmagent/sync/
  state.json
  outbox/
    evt-*.json
  acked/
    evt-*.json
  failed/
    evt-*.json
```

每个 event 有这些字段：

```json
{
  "schema_version": 1,
  "event_id": "evt-...",
  "workspace": "demo",
  "project": "alpha",
  "kind": "file_changed",
  "path": "workspaces/demo/prd/current.md",
  "sha256": "...",
  "base_revision": "rev-123",
  "created_at": "..."
}
```

这个协议需要几个能力：

- 幂等写入；
- 明确 ACK；
- 失败重试；
- transient failure 和 permanent failure 区分；
- 冲突检测；
- 本地 pending / acked / failed 留痕；
- 本地状态可恢复。

飞书 Base 可以存事件记录，但它本身不是事件 ACK 协议服务器。

如果直接把“写入 Base 成功”当成 PMAgent sync ACK，会有问题：

- 网络成功但业务字段没写完整怎么办？
- 重复写入同一个 event 怎么办？
- 写了 event 但文档镜像失败怎么办？
- 飞书 API 超时但实际写入成功怎么办？
- Base 记录被人手动改了怎么办？
- 后续 Agent 分析是否已经消费这次 event 怎么判断？

这些都需要 PMAgent 自己定义适配层。飞书不能直接替代这层协议。

### 5.2 冲突处理

PMAgent 第一版冲突策略是：

```text
local canonical wins
server is mirror/advisory
```

如果服务器和本地同一路径 hash 不一致：

1. 不自动覆盖本地；
2. 生成 `sync_conflict` inbox item；
3. 展示 diff；
4. 用户或外部 Agent 决定 accept local / accept remote / manual merge。

飞书不适合直接承担这个职责。

原因：

- 飞书 Docs 的编辑历史不是 PMAgent 的 canonical diff；
- Base 字段适合结构化状态，不适合保存完整文件冲突；
- 人可以在飞书里直接改内容，造成远端内容变化；
- 飞书权限和编辑记录不能直接映射到 Git / file hash 的冲突模型；
- Agent 需要的是明确的 local path、sha256、base_revision 和 diff。

所以飞书只能作为冲突提示和人工协作界面，不能作为冲突裁判。

### 5.3 Server Agent 调度

文档中的 Server Agent 不是简单的“把建议存在某个地方”。

它需要：

- 读取同步快照；
- 选择分析时机；
- 根据关键文件变化提高优先级；
- 异步 enqueue analyze job；
- 生成 suggestion；
- 记录 suggestion policy version；
- 收集反馈；
- 后续离线复盘 policy。

飞书 CLI 可以帮 Agent 读写飞书，但飞书本身不是 Agent runtime。

也就是说，仍然需要某个执行者：

- 本地 daemon；
- CI job；
- 云函数；
- 自建轻量服务；
- Codex / Claude Code 触发的定时任务；
- 后续的 PMAgent server worker。

飞书可以存输入和输出，但不能替你稳定调度和运行 Server Agent。

### 5.4 权威状态 current-state

PMAgent 的 `current-state.json` 不只是展示数据，它是外部 Agent 判断下一步的协议输入，包括：

- active_skill；
- recommended_skills；
- inbox；
- async_runs；
- server_sync；
- dev；
- artifacts；
- readiness。

这些字段可以同步到飞书展示，但不应该让飞书成为它们的唯一来源。

原因：

- 外部 Agent 在本地工作，需要稳定读取本地协议文件；
- readiness / recommended_skills 依赖本地文件扫描和 registry；
- hooks / guard 保护的是本地 canonical artifact；
- 本地无网时仍应可恢复；
- 飞书字段结构变动不应该破坏本地 Agent 工作协议。

所以正确关系是：

```text
本地 current-state.json -> 同步摘要到飞书
飞书 feedback / suggestion -> pull 回本地 inbox
```

而不是：

```text
飞书 Base = current-state.json
```

### 5.5 测试和可重复性

如果自建一个最小 FastAPI + SQLite server，本地测试可以这样做：

```text
启动 test server
push event
断言 ack
pull suggestion
断言 inbox
模拟 conflict
断言 sync_conflict
```

如果飞书直接作为 server，测试会依赖：

- 飞书租户；
- 应用权限；
- OAuth token；
- Base 表结构；
- 网络；
- API 限流；
- 飞书接口行为；
- 测试数据清理。

这会让核心同步协议更难做稳定回归。

所以即便最终用飞书，也应该先把 `server_sync.py` 写成可测试的抽象接口，然后实现 `FeishuBackend`。

## 6. 推荐架构

推荐架构如下：

```text
PMAgent local workspace
  Requirement.md
  prd/current.md
  decisions/
  research/
  dev/
  .pmagent/current-state.json
  .pmagent/sync/outbox
  .pmagent/inbox

        |
        v

server_sync.py
  SyncBackend interface
    - push_event(event)
    - push_file(path, content, sha256)
    - pull_snapshot(workspace)
    - pull_suggestions(workspace)
    - send_feedback(suggestion_id, status)

        |
        v

FeishuBackend
  Base: projects / workspaces / artifacts / events / suggestions / feedback / dev_status
  Docs/Wiki: readable mirrors of Requirement / PRD / decisions / dev-plan
  IM: notifications and action cards
```

这个架构保留了 PMAgent 的协议内核，同时用飞书替代自建 UI 和协作层。

## 7. 数据映射建议

### 7.1 Base 表设计

#### Projects

| 字段 | 说明 |
|---|---|
| project_id | PMAgent project id |
| name | 项目名 |
| owner | 负责人 |
| status | active / archived |
| created_at | 创建时间 |
| updated_at | 更新时间 |

#### Workspaces

| 字段 | 说明 |
|---|---|
| workspace_id | PMAgent workspace |
| project_id | 所属项目 |
| phase | clarifying / researching / prd / dev / maintenance |
| readiness_score | 当前 readiness |
| active_skill | 当前工作面 |
| pending_inbox_count | 待处理 inbox 数 |
| last_push_at | 最近同步时间 |

#### Artifacts

| 字段 | 说明 |
|---|---|
| artifact_id | artifact id |
| workspace_id | workspace |
| kind | requirement / prd / decision / research / dev-plan / slice |
| local_path | 本地路径 |
| sha256 | 内容 hash |
| feishu_doc_url | 飞书镜像文档 |
| revision | 本地 revision |
| updated_at | 更新时间 |

#### Events

| 字段 | 说明 |
|---|---|
| event_id | PMAgent event id |
| workspace_id | workspace |
| kind | file_changed / state_changed / feedback_sent |
| local_path | 相关路径 |
| sha256 | 内容 hash |
| base_revision | 基准 revision |
| sync_status | pending / acked / failed / conflict |
| error | 错误信息 |
| created_at | 创建时间 |

#### Suggestions

| 字段 | 说明 |
|---|---|
| suggestion_id | suggestion id |
| workspace_id | workspace |
| kind | research / debate / observation / prd / dev / process |
| title | 标题 |
| reason | 建议理由 |
| evidence | 证据摘要 |
| recommended_skill | 推荐 skill |
| status | pending / accepted / ignored / deferred |
| policy_version | suggestion policy version |
| created_at | 创建时间 |

#### Feedback

| 字段 | 说明 |
|---|---|
| feedback_id | feedback id |
| suggestion_id | suggestion id |
| workspace_id | workspace |
| signal | explicit_user_accept / ignore / defer |
| actor | 操作者 |
| created_at | 创建时间 |

### 7.2 Docs / Wiki 映射

| 本地文件 | 飞书形态 | 语义 |
|---|---|---|
| `Requirement.md` | Docs 或 Wiki 节点 | 可读镜像 |
| `prd/current.md` | Docs 或 Wiki 节点 | 可读镜像 |
| `decisions/*.md` | Docs 子页面 | 决策记录 |
| `research/*.md` | Docs 子页面 | 调研摘要 |
| `dev/dev-plan.md` | Docs 页面 | 开发计划 |
| `dev/slices/*.md` | Base 记录 + Docs 页面 | slice 任务 |

### 7.3 IM 映射

| 事件 | 通知 |
|---|---|
| PRD 更新 | 群消息摘要 |
| suggestion 生成 | 消息卡片 |
| dev blocked | @负责人 |
| sync conflict | 高优先级提醒 |
| inbox pending 太多 | 每日摘要 |

## 8. 推荐落地阶段

### 阶段一：飞书只做只读镜像

目标：

- 验证飞书 CLI / API 权限；
- 建立 Base 表；
- 把本地 current-state、Requirement、PRD、dev status 推到飞书；
- 不从飞书反向写本地。

允许：

- 本地 -> 飞书；
- 飞书展示；
- 飞书通知。

禁止：

- 飞书 -> 本地覆盖；
- 人在飞书改 PRD 后自动写回；
- 飞书作为唯一状态源。

验收标准：

- 本地同步失败不影响主流程；
- 飞书内容能展示项目状态；
- Base 中能看到 artifact sha256 和更新时间；
- 重复 push 不产生重复主记录；
- 无权限时本地生成 `server_sync.last_error`。

### 阶段二：suggestion 回流

目标：

- 从飞书 Base 拉取 pending suggestion；
- 转成本地 inbox item；
- 用户在本地 accept / ignore / defer；
- feedback 写回飞书。

允许：

- 飞书 Suggestions -> 本地 inbox；
- 本地 feedback -> 飞书 Feedback。

仍然禁止：

- suggestion 自动改 PRD；
- suggestion 自动触发 research / debate / observation；
- feedback 自动改 prompt。

验收标准：

- `pmagent review` 能看到飞书 suggestion；
- accept 后本地 inbox 状态更新；
- 飞书 Suggestions 状态同步为 accepted；
- 飞书 Feedback 记录 policy_version 和 actor。

### 阶段三：Server Agent 分析

目标：

- Server Agent 读取飞书 Base / Docs 快照；
- 生成 suggestion；
- 写入飞书 Suggestions；
- 本地 pull 回 inbox。

执行方式可以先用：

- 本地命令手动触发；
- 定时脚本；
- CI job；
- 后续再迁移到真正 server worker。

验收标准：

- 分析不阻塞本地 push；
- suggestion 包含 evidence；
- 每条 suggestion 有 policy_version；
- 低质量 suggestion 可 ignore 并记录反馈；
- accepted signal 只用于后续离线复盘。

### 阶段四：谨慎考虑飞书反向编辑

只有当前三阶段稳定后，才考虑：

- 人在飞书修改 PRD；
- PMAgent 检测到远端变更；
- 生成 `sync_conflict`；
- 用户选择是否合并。

不要做自动覆盖。

## 9. “为什么不可以完全替代”的本质原因

不是飞书能力不够，而是二者抽象层级不同。

飞书是协作平台：

```text
人、文档、表格、消息、权限、评论、组织协同
```

PMAgent 服务器层是协议边界：

```text
artifact/event sync、state snapshot、inbox、suggestion feedback、conflict policy、Agent-readable contract
```

飞书可以承载协议产生的数据，但不等于协议本身。

如果强行完全替代，会导致：

1. 本地 canonical 和飞书文档双主写入；
2. sync ACK 语义模糊；
3. conflict 无法稳定判断；
4. Agent 分析调度仍要另找地方跑；
5. 测试依赖外部 SaaS；
6. 权限和提示注入风险扩大；
7. PMAgent 从“文件协议层”退化成“飞书自动化脚本集合”。

最后一点最重要。

你的三层文档里已经明确 PMAgent 不是 Agent Runner，也不是靠大量 CLI 驱动的 PM 软件，而是：

```text
嵌在 Claude Code / Codex / Kiro 等外部 Agent CLI 里的工作流协议、文件协议、状态协议和协作规范层。
```

如果把服务器层完全飞书化，PMAgent 的协议内核会被飞书产品模型反向绑架。

## 10. 最终建议

推荐把原设计改成：

```text
Server layer
  = Sync protocol + Inbox protocol + Suggestion protocol + Backend adapters

Backend adapters
  - LocalFastAPIBackend
  - FeishuBackend
  - FutureCloudBackend
```

第一版可以不做 LocalFastAPIBackend 的完整 UI，只做 FeishuBackend：

```text
本地 canonical artifacts
  -> PMAgent sync protocol
  -> FeishuBackend
  -> 飞书 Base / Docs / IM
```

但不要删除这些 PMAgent 内部概念：

- `server_sync.py`
- `.pmagent/sync/outbox`
- `event_id`
- `sha256`
- `base_revision`
- `acked / failed / conflict`
- `inbox`
- `sync_conflict`
- `suggestion_id`
- `feedback_signal`
- `policy_version`

这些是 PMAgent 自己的协议骨架。飞书应该挂在这个骨架上，而不是替代这个骨架。

## 11. 最稳妥的产品表述

可以对外这样描述：

```text
PMAgent 支持飞书作为协作后端。

本地文件仍是 Agent 工作协议和 canonical source。
飞书用于团队看板、文档镜像、建议卡片、通知和反馈收集。
```

不要描述成：

```text
PMAgent 的服务器层改成飞书。
```

前者是可控的架构扩展，后者会让用户以为飞书是权威数据层、同步协议层和 Agent 调度层。

## 12. 结论

飞书方案值得做，而且很适合 PMAgent 当前方向。

但正确做法是：

```text
用飞书替代自建协作界面，而不是替代 PMAgent 协议服务器。
```

短期最优解：

1. 保留本地文件为 canonical；
2. 保留 PMAgent 的 sync / inbox / suggestion 协议；
3. 新增 `FeishuBackend`；
4. 把飞书 Base 作为看板；
5. 把飞书 Docs / Wiki 作为文档镜像；
6. 把飞书 IM 作为通知和建议卡片入口；
7. 禁止飞书自动覆盖本地 canonical artifact；
8. 所有远端变化先进入 inbox，由用户或外部 Agent review。

这样既能吃到飞书生态红利，又不会破坏 PMAgent 三层模型里最关键的协议边界。
