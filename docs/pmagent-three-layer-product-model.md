# PM Agent 三层协作模型：主流程、文件协作层、开发端

> 本文用于整理当前产品思路，不是实施计划、排期或任务拆解。  
> 目标是把“去 mode 化、skill 可插拔、飞书文件协作层与分析 Agent、开发端 slice 执行”放到同一个清晰模型里。
>
> 2026-04-30 修订：V1 暂不做服务器侧看板层。中间层优先定义为飞书文件协作层，保存主流程和 dev 的所有文件镜像；分析 Agent 读取飞书文件层并输出建议。表格只做机器索引和同步账本，不作为产品看板。

## 1. 核心判断

PM Agent 不应该继续被设计成一个由 `mode` 驱动的强流程系统。

真正想要的不是“把 zero-to-one 换个名字”，也不是“给现有流程再加几个命令”，而是把系统重组为三个持续交流的层面：

```text
主流程层 Mainflow
  用户按需调用 skill，逐步沉淀需求 / PRD / 决策 / 上下文
        ↕ 同步快照 / 建议卡片 / 采纳反馈
文件协作层 Feishu File Layer + Analysis Agent
  同步主流程和 dev 文件，分析 Agent 读取文件层并提出建议

主流程层 Mainflow
        ↕ PRD / dev-plan / vertical slices / 开发反馈
开发端 Dev
  消费主流程交付的 PRD，做 Dev Readiness Gate，拆 vertical slices，执行开发并反馈问题
```

注意：开发端不直接和分析 Agent 形成主写入闭环。分析 Agent 可以读取飞书上的 dev 文件并提出建议，但 dev 反馈应先回流主流程 inbox，再由主流程决定是否修改 Requirement、PRD、decision 或 dev-plan。

第一性原则：**任何设计如果不服务于这三层，以及三层之间的信息流转，就不应该成为主目标。**

---

## 2. 为什么要弱化 / 去掉 mode

当前 `mode` 的问题不是名字不好，而是它容易把 PM Agent 变成“预设流程机器”：

```text
clarify → research → strategy → PRD → testcase → export
```

但真实项目并不总是需要完整流程：

- 有些需求很小，不需要 research。
- 有些需求只需要 PRD，不需要 strategy。
- 有些项目需要先 debate，不适合先写 PRD。
- 有些项目在开发端发现问题后，需要回到 PRD，而不是继续往后走。

因此，系统需要从：

```text
mode 决定流程
```

转成：

```text
用户选择 skill
skill 产生 artifact
skill 给出软推荐
用户决定是否采纳
状态层只负责导航和展示
```

这里不是取消状态，而是取消“状态 = 强制流程锁”。

---

## 3. 主流程层：用户按需调用 skill

主流程层是用户和 Agent 共同工作的地方。它的核心体验应该是：

1. 用户看到一系列可调用 skill。
2. 用户选择当前最需要的 skill，例如“需求澄清”。
3. skill 通过对话、文件读取、分析、写入，更新主流程 artifact。
4. skill 可以推荐下一步，例如“现在可以进入 research”。
5. 用户可以听从，也可以不听从。
6. 所有关键文件变化会同步到飞书文件层。

### 3.1 主流程层不再是 mode 链

主流程不应该说：

```text
你现在处于 zero-to-one mode，所以必须先做 research。
```

而应该说：

```text
当前需求澄清度较高。
推荐下一步：research / write-prd / debate。
这些都是建议，你可以选择任意 skill。
```

### 3.2 readiness / score 的位置

readiness 和 score 可以保留，但只能作为导航信号。

它们可以回答：

- 当前需求清晰度怎么样？
- 是否有推荐的下一步？
- 哪些问题还比较薄弱？
- 当前 artifact 是否足够进入 PRD 或开发端？

但它们不应该：

- 强制用户进入某一步；
- 强制 Agent 按评分模板提问；
- 把对话变成“为了刷分而问问题”；
- 阻止用户跳过某个 skill。

### 3.3 Agent 提问和评分要解耦

一个重要原则：**评分不应过度干预 Agent 的提问。**

Agent 提问应该优先来自：

- 用户真实意图；
- 当前上下文中的矛盾；
- 需求边界；
- 业务假设；
- 文件里的缺口；
- 可能导致返工的关键不确定性。

评分可以作为背景信号，但不应该变成问题生成器。

---

## 4. Skill 的新位置：主流程的可插拔单元

新的主流程里，skill 是核心执行单元。

一个 skill 不只是 prompt，也不只是命令说明，而应该像一个小型工作协议：

```text
Skill
  - 它解决什么问题
  - 它读取哪些上下文
  - 它会产出什么 artifact
  - 它是否会修改 canonical 文件
  - 它是否可以异步运行
  - 它如何呈现结果
  - 它会推荐哪些下一步
  - 用户如何采纳 / 忽略它的结果
```

### 4.1 Step skill

这类 skill 直接推进主流程 artifact，例如：

- 需求澄清；
- 写 Requirement；
- 写 Strategy；
- 写 PRD；
- Challenge PRD；
- 写 Testcase；
- Export Dev Pack。

它们可以前后有关联，但不应该被 mode 强绑定。

### 4.2 Async skill

这类 skill 可以作为旁路异步运行，例如：

- research；
- debate；
- observation；
- competitive analysis；
- architecture review；
- PRD consistency check。

它们的特点是：

- 用户主动调用；
- 可后台执行；
- 结果落成独立 artifact；
- 结果回到主流程或飞书文件层；
- 不自动改写 PRD，除非用户接受并触发后续写入。

### 4.3 文件层分析 suggestion skill

分析 Agent 也应该有自己的 suggestion skill，用来分析同步到飞书文件层的内容并提出建议。

这个 skill 的输出不是“最终结论”，而是建议卡片：

```text
Suggestion Card
  - 建议类型：research / debate / observation / PRD 回炉 / dev slice 风险 / 流程问题
  - 为什么建议
  - 证据来自哪些文件或状态
  - 用户可以怎么处理
  - 接受 / 忽略 / 暂缓
```

---

## 5. 文件协作层：同步、索引、分析 Agent

文件协作层不是简单的数据备份层。它承担三个职责：

1. **同步主流程内容**；
2. **保存主流程和 dev 的团队可见文件**；
3. **让分析 Agent 基于文件层给出自由建议。**

### 5.1 同步层

主流程每次修改文件，都应把内容同步到飞书文件层。

同步对象可以包括：

- Requirement；
- PRD；
- research notes；
- decisions；
- debate synthesis；
- observation findings；
- dev-plan；
- slices；
- current state / readiness；
- skill run records。

飞书文件层基于这些内容形成统一文件树；表格只保存机器索引，不作为 V1 看板。

### 5.2 文件索引层

V1 暂不做看板层。文件索引层不是面向用户的主产品界面，而是给同步器和分析 Agent 使用的机器账本。

它只需要回答：

- 当前有哪些 project？
- 每个 project 下有哪些 requirement / workspace？
- 哪些需求还在澄清？
- 哪些需求已有 PRD？
- 哪些 PRD 已进入开发准备？
- 哪些 slice 正在开发？
- 哪些地方有分析 Agent 建议？
- 哪些建议被接受、忽略或暂缓？
- 哪些开发反馈需要回流 PRD？

### 5.3 分析 Agent

分析 Agent 持续分析飞书文件层中的同步内容。

它可以提出比较自由的建议，例如：

- 这里信息不足，建议 research；
- 这里有关键取舍，建议 debate；
- 这里需要持续外部信号，建议 observation；
- 当前 PRD 验收标准太弱；
- 当前需求边界不清；
- 当前 dev slice 太大；
- 当前测试策略太像实现细节；
- 当前 PM Agent 主流程本身有问题。

这个 Agent 的价值不是替用户决策，而是持续提供第二视角。

每条建议都应映射回具体流程位置，例如 Requirement、Research、Decision、PRD、Dev Readiness、Slice、Run、QA 或 Lessons。

---

## 6. 分析 Agent 的自我优化

分析 Agent 的“进化”第一版不应理解成自动修改代码或自动改 PRD。

更准确的定义是：

> 分析 Agent 有一个 suggestion skill。它根据飞书文件层内容提出建议。用户点击接受后，这条接受信号会反哺 suggestion skill，让它逐渐优化“什么情况下该提什么建议”。

### 6.1 为什么采纳信号用“用户点击接受”

因为建议类型很多元，很难统一用自动指标判断好坏。

例如：

- 一条 debate 建议是否有用，可能要几天后才知道；
- 一条 observation 建议可能只是提醒长期关注；
- 一条“PRD 边界不清”的建议可能不会直接产生代码变化；
- 一条流程问题建议可能只是改变人的判断。

所以第一版采纳信号可以很简单：

```text
用户点击接受 = 这条建议对当前上下文有价值
```

### 6.2 优化对象

被接受的建议可以优化：

- suggestion skill 的提示词；
- 建议类型的优先级；
- 触发条件；
- 项目级偏好；
- 用户偏好；
- 示例库；
- 反例库；
- 推荐文案结构。

它不必第一版就自动改：

- 主流程代码；
- canonical PRD；
- skill 源文件；
- 流程配置。

这些可以以后再说，但不是当前整体思路的中心。

---

## 7. 开发端：PRD 不是直接交给代码，而是进入 Dev Readiness Gate

开发端的核心思想来自 `2026-04-27-prd-to-dev-readiness-gate.md`：

```text
PRD
  ↓
Dev Readiness Gate
  ↓
Development Plan
  ↓
Vertical Slice Tasks
  ↓
TDD Execution
  ↓
QA / Acceptance Report
```

### 7.1 为什么不能 PRD 后直接开发

直接把 PRD 交给 AI 开发容易出现：

- 按数据库 / API / 前端水平拆任务；
- 一次性生成大量代码；
- 缺少短反馈回路；
- 测试锁实现细节，不锁用户行为；
- PRD 里的产品语言没有转成工程接口；
- 人类判断和可离线执行任务混在一起。

### 7.2 Dev Readiness Gate 的职责

Dev Readiness Gate 不是替代 PRD。

它负责把 PRD 转译成工程可执行包：

- implementation decisions；
- testing decisions；
- out of scope；
- deep module opportunities；
- domain language；
- vertical slices；
- first AFK slice；
- HITL / AFK 标记；
- public behavior tests。

### 7.3 Vertical slice

开发端任务应该按用户可观察结果切，而不是按技术层切。

坏切法：

```text
1. 设计数据库
2. 写 API
3. 写前端
4. 写测试
```

好切法：

```text
1. 用户可以完成最小创建路径
2. 用户可以编辑刚创建的对象
3. 用户可以处理失败 / 权限 / 重复提交
```

每个 slice 应该足够薄、可独立验证、最好可独立 demo。

### 7.4 开发反馈回流

开发端不是主流程的终点。

当开发中发现：

- PRD 缺少边界；
- 验收标准不可测；
- slice 太大；
- 测试策略错误；
- 某个领域词不稳定；
- 架构决策缺失；

就应该回流到 PRD / 主流程，而不是在开发端硬编码补洞。

---

## 8. 三层之间的信息流

### 8.1 主流程 → 文件协作层

主流程把文件和状态同步到飞书文件层：

```text
Requirement / PRD / decisions / research / debate / observation / readiness / skill runs
```

分析 Agent 据此触发分析；表格只记录索引、任务和反馈，不做 V1 看板。

### 8.2 文件协作层 → 主流程

分析 Agent 通过建议卡片把分析结果反馈给用户：

```text
建议 research
建议 debate
建议 observation
建议 PRD 回炉
建议补充验收标准
建议拆 slice
建议处理流程问题
```

用户接受后，可回到主流程调用对应 skill。

### 8.3 主流程 → 开发端

当 PRD 足够稳定，用户调用生成 PRD / export / dev readiness 相关 skill，将 PRD 交给开发端。

输出不是“直接写代码”，而是：

```text
PRD + Dev Plan + Slice Tasks + Test Plan
```

### 8.4 开发端 → 主流程 / 文件协作层

开发端持续回传：

- slice 状态；
- TDD 状态；
- QA 结果；
- blocked reasons；
- PRD 缺口；
- 需要 human decision 的事项。

这些内容同步到飞书文件层，也可以回到主流程继续打磨 PRD。

---

## 9. 当前测试体系给出的信号

当前项目有 175 个 tests，全部通过。

它们不是“大多数没用”，但很多是在保护当前 mode-era 系统表面，例如：

- `route_mode`；
- `mode_skill_path`；
- CLI 输出文案；
- markdown table 字符串；
- 当前文件协议细节。

这些测试对小改动有用，但对三层重构会形成阻力。

新的测试重心应该从：

```text
mode 是否显示正确
某段文案是否完全一致
某个固定流程是否按顺序走
```

转成：

```text
skill contract 是否稳定
推荐是否非强制
异步 skill 是否不污染 canonical artifact
analysis suggestion 是否可接受 / 忽略
PRD 是否能进入 dev readiness
slice 是否可独立验收
开发反馈是否能回流
```

也就是说，测试应该保护三层系统的不变量，而不是保护旧流程外壳。

---

## 10. 最终形态的一句话

PM Agent 应该从一个“mode 驱动的本地 PM 流程 CLI”，演变成一个：

> **以可插拔 skill 为主流程，以飞书文件协作层和分析 Agent 为中间层，以 Dev Readiness Gate 和 vertical slices 为开发入口的三层 PM-to-dev 系统。**

它的核心体验不是“系统告诉你必须去哪一步”，而是：

```text
你可以调用任何合适的 skill；
系统持续记录状态；
分析 Agent 持续给你第二视角；
开发端把 PRD 转成可执行 slices；
所有反馈都能回到主流程继续完善。
```

---

## 11. 当前最重要的概念边界

| 概念 | 新定位 |
|---|---|
| mode | 不再是主流程核心；最多作为旧版 preset / bundle 存在 |
| phase | 可以保留为状态维度，但不强制流程 |
| readiness | 导航信号，不是 gate lock |
| recommended next step | 软推荐，不自动跳转 |
| skill | 主流程核心可插拔执行单元 |
| async skill | 用户主动调用的旁路任务 |
| analysis Agent | 第二视角建议者，不是自动决策者 |
| suggestion accepted | 用户点击接受 |
| Agent evolution | 优化 suggestion skill 的建议能力 |
| PRD handoff | 进入 Dev Readiness Gate，而不是直接开发 |
| dev slice | 面向用户可观察行为的垂直切片 |

---

## 12. 本文没有展开的内容

本文刻意不展开实施计划，包括：

- 具体代码怎么改；
- 数据库 schema；
- API 设计；
- 前端页面设计；
- 迁移步骤；
- 测试重写顺序；
- server 技术栈；
- 多 Agent 调度细节。

这些应在整体思路稳定后，再进入单独的架构设计或 PRD。
