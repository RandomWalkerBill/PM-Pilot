# 飞书 CLI 能力调研报告

调研日期：2026-04-29

## 1. 结论摘要

飞书 CLI 当前主要指官方开源项目 `larksuite/cli`，命令二进制名为 `lark-cli`，npm 包名为 `@larksuite/cli`。它不是单一业务工具，而是飞书开放平台的一层命令行操作面，面向人类开发者和 AI Agent 同时设计。

截至本次调研，官方 GitHub Release 最新版本为 `v1.0.21`，发布时间为 2026-04-28。官方 GitHub README 显示其覆盖 16 个业务域、200+ 精选命令、23 个 AI Agent Skills，并支持通过原始 API 层访问 2500+ 飞书开放平台端点。

核心判断：

- 如果目标是让 AI Agent 稳定操作飞书，官方 `lark-cli` 是当前最正统、覆盖最广的入口。
- 如果目标是高保真 Markdown 与飞书文档双向转换，第三方 `riba2534/feishu-cli` 值得单独评估，它在文档转换和图表处理上更专门。
- `lark-cli` 的价值不只在 CLI 本身，更在于它把飞书的权限、身份、OpenAPI、Agent Skills 和安全边界包装成可被 AI 调用的稳定接口。

## 2. 调研范围与口径

本报告重点调研官方飞书 / Lark CLI：

- 官方仓库：https://github.com/larksuite/cli
- 官方 Release：https://github.com/larksuite/cli/releases
- 官方 Changelog：https://github.com/larksuite/cli/blob/main/CHANGELOG.md
- 官方中文站：https://feishu-cli.com/zh/

同时对比第三方同名工具：

- 第三方仓库：https://github.com/riba2534/feishu-cli

注意：中文语境中的“飞书 CLI”容易混用。官方项目的命令是 `lark-cli`，第三方项目的命令是 `feishu-cli`。二者能力有重叠，但定位不同。

## 3. 官方 lark-cli 的定位

官方 `lark-cli` 是飞书开放平台的命令行工具，目标用户包括：

- 需要脚本化操作飞书的开发者。
- 需要在 CI、自动化流程中调用飞书 API 的工程团队。
- 需要让 Claude Code、Cursor、Codex、OpenCode 等 AI Agent 操作飞书的用户。
- 需要跨文档、消息、日历、任务、多维表格等业务域编排工作流的团队。

它的设计重点是“Agent-native”：命令参数尽量清晰，输出支持结构化格式，并提供 Skills，让 Agent 不必临时猜测 API 参数和权限模型。

## 4. 三层命令体系

官方 `lark-cli` 将能力分成三层。

| 层级 | 说明 | 适用场景 | 示例 |
|---|---|---|---|
| 快捷命令 | 使用 `+` 前缀，对常见任务做高层封装 | 人类日常使用、Agent 首选 | `lark-cli calendar +agenda` |
| API 命令 | 从飞书 OAPI 元数据生成，与平台端点一一对应 | 需要精确控制参数和行为 | `lark-cli calendar events instance_view --params '{...}'` |
| 原始 API | 直接发起 HTTP 风格的开放平台 API 调用 | 快捷命令未覆盖、探索新 API | `lark-cli api GET /open-apis/calendar/v4/calendars` |

这一设计的优势是：简单任务走快捷命令，复杂任务走 API 命令，极端或新需求走原始 API，不需要频繁切换工具。

## 5. 安装、配置与认证

推荐安装方式：

```bash
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g
```

国内网络环境可使用 npm 镜像：

```bash
npm install -g @larksuite/cli --registry=https://registry.npmmirror.com
```

初始化和登录：

```bash
lark-cli config init
lark-cli auth login --recommend
lark-cli auth status
lark-cli doctor
```

Agent 模式下也支持无头流程，例如输出授权 URL，由用户在浏览器中完成确认：

```bash
lark-cli config init --new
lark-cli auth login --recommend
```

认证能力包括：

- OAuth 登录。
- 登录状态检查。
- 退出登录并清理本地凭证。
- 查看已授权 scope。
- 检查指定 scope 是否存在。
- 多身份切换：用户身份和机器人身份。

身份切换示例：

```bash
lark-cli calendar +agenda --as user
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "hello"
```

## 6. 业务能力清单

| 业务域 | 主要能力 |
|---|---|
| Messenger / IM | 发送消息、回复消息、群聊创建和管理、历史消息读取、消息搜索、话题消息、表情反应、图片和文件下载 |
| Docs | 创建、读取、更新、搜索文档，支持 Markdown 内容，支持媒体插入和读取 |
| Drive | 上传下载文件、搜索文档和知识库、导入导出、评论、权限申请与管理 |
| Base / 多维表格 | 表、字段、记录、视图、仪表盘、工作流、表单、角色和权限、数据聚合与分析 |
| Sheets | 创建表格、读取、写入、追加、查找、导出 XLSX / CSV，支持图片和样式类能力 |
| Slides | 创建和管理演示文稿，读取内容，新增、删除、替换幻灯片，支持媒体和字体相关能力 |
| Calendar | 查看日程、创建事件、邀请参会者、忙闲查询、时间建议、会议室查找、事件更新 |
| Mail | 浏览、搜索、读取邮件，发送、回复、转发，草稿管理，新邮件监听，签名、回执、模板 |
| Tasks | 创建、查询、更新、完成任务，管理任务列表、子任务、评论、提醒和成员分配 |
| Wiki | 知识空间、节点、文档创建和管理，节点移动、删除、权限相关操作 |
| Contact | 按姓名、邮箱、手机号搜索用户，读取用户资料 |
| Meetings / VC | 搜索会议记录，查询会议纪要、录制、会议关联文档 |
| Minutes | 获取妙记元数据、摘要、待办、章节、逐字稿和媒体文件 |
| Attendance | 查询个人考勤打卡记录 |
| Approval | 查询审批任务，审批、拒绝、转交、撤销和抄送审批实例 |
| OKR | 查询、创建、更新 OKR，管理目标、关键结果、对齐、指标和进度记录 |
| Project / Meegle | 项目管理能力通过独立 `meegle-cli` 提供，需要另行安装 |

## 7. AI Agent Skills 能力

官方 README 当前列出的 Skills 包括：

| Skill | 能力说明 |
|---|---|
| `lark-shared` | 应用配置、认证登录、身份切换、scope 管理、安全规则，供其他 Skill 共享 |
| `lark-calendar` | 日历事件、日程视图、忙闲查询、时间建议 |
| `lark-im` | 消息发送和回复、群聊管理、消息搜索、媒体上传下载、表情反应 |
| `lark-doc` | 文档创建、读取、更新、搜索，基于 Markdown |
| `lark-drive` | 文件上传下载、权限和评论管理 |
| `lark-sheets` | 表格创建、读写、追加、查找、导出 |
| `lark-slides` | 演示文稿创建和管理，读取内容，增删幻灯片 |
| `lark-base` | 多维表格、字段、记录、视图、仪表盘、数据分析 |
| `lark-task` | 任务、任务列表、子任务、提醒、成员分配 |
| `lark-mail` | 邮件浏览、搜索、读取、发送、回复、转发、草稿和监听 |
| `lark-contact` | 用户搜索和用户资料读取 |
| `lark-wiki` | 知识空间、节点、文档管理 |
| `lark-event` | WebSocket 实时事件订阅、正则路由、Agent 友好格式 |
| `lark-vc` | 会议记录搜索、会议纪要摘要、待办、逐字稿 |
| `lark-whiteboard` | 白板和图表 DSL 渲染 |
| `lark-minutes` | 妙记元数据和 AI 产物 |
| `lark-openapi-explorer` | 从官方文档探索底层 API |
| `lark-skill-maker` | 自定义 Skill 创建框架 |
| `lark-attendance` | 查询个人考勤打卡记录 |
| `lark-approval` | 查询、审批、拒绝、转交、撤销和抄送审批 |
| `lark-workflow-meeting-summary` | 会议纪要聚合和结构化报告工作流 |
| `lark-workflow-standup-report` | 日程和待办汇总工作流 |
| `lark-okr` | OKR 查询、创建、更新和进度管理 |

这些 Skills 的实际价值在于：Agent 可以基于 Skill 文档选择正确命令、理解权限前置条件，并避免直接拼接复杂 OpenAPI 请求。

## 8. 输出、分页与可组合性

`lark-cli` 支持多种输出格式：

```bash
--format json
--format pretty
--format table
--format ndjson
--format csv
```

分页能力：

```bash
--page-all
--page-limit 5
--page-delay 500
```

这使它适合进入自动化流水线：

- `json` 适合 Agent 和脚本解析。
- `ndjson` 适合流式处理。
- `csv` 适合导出到表格或数据分析流程。
- `table` / `pretty` 适合人工查看。

## 9. 安全设计与风险

官方 README 明确提示：该工具可被 AI Agent 调用，一旦授权，Agent 会在授权范围内代表用户操作飞书数据，因此天然存在误操作、数据泄漏、提示注入等风险。

已有安全设计：

- 凭证存储在操作系统原生密钥链中，不以明文保存在普通配置文件。
- 支持最小权限授权，`--recommend` 可选择常见操作所需 scope。
- 支持用户身份和机器人身份切换。
- 写操作可使用 `--dry-run` 预览请求。
- 支持输入校验、输出净化，降低命令注入和终端注入风险。
- 邮件 Skill 对邮件正文这类不可信输入有专门提示注入防护规则。

建议使用边界：

- 不要给 Agent 一次性授权全量权限。
- 生产环境先使用只读 scope 验证。
- 让机器人保持私聊助手形态，谨慎加入大群。
- 对发送消息、修改文档、写 Base、发邮件、审批等写操作默认先 `--dry-run`。
- 为不同 Agent 或不同项目隔离凭证和应用。

## 10. 与第三方 riba2534/feishu-cli 的对比

| 维度 | 官方 `larksuite/cli` | 第三方 `riba2534/feishu-cli` |
|---|---|---|
| 维护方 | Lark Suite / 字节跳动官方团队 | 社区作者 |
| 命令名 | `lark-cli` | `feishu-cli` |
| 定位 | 飞书开放平台通用 CLI，Agent-native | 飞书开放平台 CLI，突出 Markdown 与文档转换 |
| 覆盖面 | 官方 README 显示 16 业务域、200+ 命令、23 Skills | 覆盖文档、知识库、表格、消息、日历、任务、会议、邮件等 |
| 文档转换 | 支持 Markdown 文档创建、读取、更新 | 核心卖点是 Markdown 与飞书文档双向高保真转换 |
| 图表能力 | 有 whiteboard / media / doc 相关能力 | 强调 Mermaid、PlantUML 转飞书画板，且可编辑 |
| 权威性 | 官方项目，OpenAPI 同步和长期兼容性更可信 | 功能深入，但长期维护和兼容性需持续观察 |
| 推荐用途 | Agent 操作飞书、企业自动化、广覆盖场景 | 高保真文档导入导出、复杂 Markdown 和图表迁移 |

结论：二者不是简单替代关系。官方 `lark-cli` 适合作为通用自动化底座，第三方 `feishu-cli` 适合作为文档转换专项工具。

## 11. 可落地场景

### 11.1 每日简报自动化

流程：

1. 从监控、工单、Base 或外部数据源汇总信息。
2. 生成 Markdown 简报。
3. 创建飞书文档。
4. 推送到指定群聊。

涉及能力：

- `lark-doc`
- `lark-im`
- `lark-base`

### 11.2 会议闭环自动化

流程：

1. 查询最近会议和妙记。
2. 提取摘要、待办、决策和风险。
3. 生成跟进文档。
4. 创建任务并分配负责人。
5. 向群聊发送跟进通知。

涉及能力：

- `lark-vc`
- `lark-minutes`
- `lark-doc`
- `lark-task`
- `lark-im`

### 11.3 多维表格数据巡检

流程：

1. 读取 Base 表和视图。
2. 检查必填字段、状态流转、负责人缺失和异常值。
3. 生成巡检报告。
4. 写回标记字段或发送修复通知。

涉及能力：

- `lark-base`
- `lark-doc`
- `lark-im`

### 11.4 邮件处理和候选人入库

流程：

1. 搜索或监听新邮件。
2. 提取附件和正文。
3. 用 Agent 总结候选人信息。
4. 写入 Base。
5. 生成回复草稿或发送确认邮件。

涉及能力：

- `lark-mail`
- `lark-drive`
- `lark-base`

### 11.5 飞书知识库维护

流程：

1. 从本地 Markdown 或已有文档生成标准化内容。
2. 创建或更新 Wiki 节点。
3. 调整权限。
4. 发布变更通知。

涉及能力：

- `lark-doc`
- `lark-wiki`
- `lark-drive`
- `lark-im`

## 12. 采用建议

建议按三个阶段引入。

### 阶段一：只读验证

目标是验证认证、权限和读取能力。

推荐命令：

```bash
lark-cli auth status
lark-cli calendar +agenda
lark-cli task +get-my-tasks
lark-cli docs +fetch --help
lark-cli schema im.messages.create
```

验收标准：

- CLI 可正常安装。
- 用户或机器人认证可完成。
- `auth status` 显示有效登录。
- 日历、任务、文档等只读命令可执行。
- Agent 能理解 Skill 并选择正确命令。

### 阶段二：低风险写入

目标是验证写操作，但限制在测试群、测试文档、测试 Base 中。

推荐动作：

- 给测试群发送消息。
- 创建测试文档。
- 创建测试任务。
- 向测试 Base 写入记录。

要求：

- 写操作先使用 `--dry-run`。
- 单独创建测试用自建应用。
- scope 只授权本阶段需要的域。

### 阶段三：工作流编排

目标是把多个飞书能力连接起来，形成真实业务闭环。

优先场景：

- 会议纪要转任务。
- 每日简报推送。
- Base 巡检和提醒。
- 邮件候选人入库。
- Wiki 文档维护。

要求：

- 明确失败重试策略。
- 对写操作做审计日志。
- 高风险动作保留人工确认。
- 生产群聊和文档权限单独隔离。

## 13. 关键风险清单

| 风险 | 说明 | 缓解方式 |
|---|---|---|
| 权限过大 | Agent 获权后可在授权范围内读写真实企业数据 | 最小 scope、测试应用、分身份授权 |
| 身份混淆 | 用户身份和机器人身份权限差异大，同一 API 可能一个成功一个失败 | 命令中显式使用 `--as user` 或 `--as bot` |
| OpenAPI 限制 | 某些 API 受企业权限、应用可见范围、群成员身份影响 | 使用 `auth check`、`schema`、官方错误码定位 |
| 版本变化快 | 项目从 2026-03-28 首次开源到 2026-04-28 已多个版本 | 固定版本、关注 Changelog、升级前回归测试 |
| Agent 误操作 | 模型可能误判用户意图或目标资源 | `--dry-run`、白名单资源、人工确认高风险写操作 |
| 提示注入 | 邮件、消息、文档内容可能诱导 Agent 执行越权动作 | 将外部内容视为不可信输入，限制工具调用范围 |

## 14. 对 PMAgent 类产品的启示

如果 PMAgent 需要接入飞书，官方 `lark-cli` 可以作为低成本集成路径：

- 不需要先开发完整飞书 SDK 封装。
- 可以通过 CLI + Skill 让 Agent 直接使用飞书能力。
- 复杂需求可先用 `lark-openapi-explorer` 探索，再沉淀成项目内 Skill 或工具层。
- 可把飞书作为项目管理 Agent 的外部执行面：读会议、写任务、更新 Base、推送进展、维护知识库。

推荐优先集成的能力顺序：

1. `lark-doc`：生成和维护项目文档。
2. `lark-task`：创建、查询和更新任务。
3. `lark-im`：向项目群推送进展和风险。
4. `lark-base`：结构化记录需求、缺陷、风险和决策。
5. `lark-calendar` / `lark-vc` / `lark-minutes`：会议和纪要闭环。

## 15. 参考链接

- 官方 GitHub 仓库：https://github.com/larksuite/cli
- 官方 Release：https://github.com/larksuite/cli/releases
- 官方 Changelog：https://github.com/larksuite/cli/blob/main/CHANGELOG.md
- 官方中文介绍页：https://feishu-cli.com/zh/
- 第三方 `riba2534/feishu-cli`：https://github.com/riba2534/feishu-cli
