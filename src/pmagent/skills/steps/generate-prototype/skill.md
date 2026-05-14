# Skill: 生成交互原型（PRD → HTML Prototype）

## Description

**把已有 PRD 转成可视化 HTML 原型，用“先看原型再谈逻辑”的方式发现问题。**

## 触发条件

- 用户要求基于已有 PRD 生成原型 / 交互 / 可视化页面
- PRD 定稿后，用户选择"设计稿对齐"（选项 B）
- 用户说"生成原型"、"出交互"、"做 prototype" 等

## 核心理念

> **原型先行验证**：通过高保真 HTML 原型让用户"看图说话"，直观发现逻辑漏洞。
> **PRD 与原型双向联动**：原型支持 Focus Mode 沙盒切片，可嵌入 PRD 实现"所见即逻辑"。

借鉴自 [Agile-PM-Workflow](https://github.com/chyxin071-sys/Agile-PM-Workflow) 的原型生成 + iframe 沙盒切片思路，适配本仓库"已有 PRD → 产出原型"的场景。

## 前置检查

1. **定位 PRD 来源**：确认 `workspaces/<workspace>/prd/` 或 `exports/vN/` 中已有 PRD 文件。
2. **提取页面清单**：从 PRD 的"交互与体验"或"详细需求"章节，提取所有页面/视图定义。
3. **确认范围**：向用户确认是全量页面还是单个核心页面。

## 执行步骤

### Step 1: 页面信息结构化

从 PRD 中提取并整理：

| 维度 | 抽取内容 |
|------|---------|
| 页面列表 | 所有页面名称 + 一句话描述 |
| 页面层级 | 导航关系（A → B → C）、入口/出口 |
| 关键交互 | 每页的核心动作（按钮、拖拽、切换） |
| 状态变体 | 空状态、加载中、错误态、正常态 |
| 数据结构 | 页面需要展示的模拟数据（字段 + 示例值） |

输出"原型范围确认清单"，**等待用户确认**后进入下一步。

### Step 2: 产出 HTML 原型

#### 2.1 技术规范

- **单文件 HTML**：所有 CSS + JS 内联，可浏览器直接打开。
- **Tailwind CSS**（CDN 引入），现代简洁设计风格。
- **Hash 路由切片**：通过 `#page-name` 实现页面切换。
  ```javascript
  // 路由示例
  window.addEventListener('hashchange', () => {
    const page = location.hash.slice(1) || 'home';
    document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
    document.getElementById(`page-${page}`)?.classList.remove('hidden');
  });
  ```
- **Focus Mode（沙盒锁定）**：支持 `?focus=feature_id` URL 参数。
  ```javascript
  // Focus Mode 示例
  const params = new URLSearchParams(location.search);
  const focusId = params.get('focus');
  if (focusId) {
    document.querySelectorAll('[data-feature]').forEach(el => {
      if (el.dataset.feature !== focusId) {
        el.style.pointerEvents = 'none';
        el.style.opacity = '0.3';
      }
    });
  }
  ```
- **交互状态**：用原生 JS 实现关键交互（弹窗、展开/收起、Tab 切换、数据联动）。
- **模拟数据**：使用贴近真实的 mock 数据，不用 lorem ipsum。

#### 2.2 设计原则

- 布局清晰，间距一致（Tailwind 的 space/gap 系统）
- 色彩克制：主色 + 中性色 + 强调色（不超过 3 种）
- 字体层级：H1 → H2 → body → caption，行高 1.5-1.6
- 响应式：Web 端默认 `max-width: 1280px` 居中布局
- 如果是移动端：固定 `375×812` 视口

#### 2.3 文件命名与存放

```
workspaces/<workspace>/exports/vN/
├── prototype.html          # 原型文件
├── YYYY-MM-DD-xxx-prd.md   # 已有 PRD
└── YYYY-MM-DD-xxx-prd.html # [可选] 内嵌原型的 HTML 版 PRD
```

### Step 3: 用户审查与迭代 【核心循环】

原型产出后：

1. **引导审查**：提示用户浏览器打开原型，并针对性地提问：
   - "这个页面的核心操作流畅吗？有没有缺少的按钮或反馈？"
   - "空状态/异常情况的提示是否覆盖到了？"
   - "信息层级是否清晰？最重要的操作是否最显眼？"
2. **收集反馈**：等待用户反馈。
3. **同步更新**：每次修改原型时，**必须执行 sync-prd-prototype skill**，确保 PRD.md、PRD-interactive.html、prototype.html 三文件一致。如果涉及功能逻辑变更，三个文件都要同步更新。
4. **循环**：重复 1-3 直到用户满意。

### Step 4: [可选] 生成内嵌原型的 HTML 版 PRD

当用户满意原型后，可选择产出一份 **HTML 格式的 PRD**，将原型以 iframe 沙盒切片方式嵌入：

#### 4.1 沙盒切片规范

每个核心功能模块采用以下结构：

```html
<div class="feature-module">
  <h3>功能：[功能名]</h3>
  <div style="display: flex; gap: 24px; align-items: flex-start;">
    <!-- 左侧：规则描述 -->
    <div style="flex: 1; min-width: 300px;">
      <h4>交互流程</h4>
      <!-- Mermaid 流程图 -->
      <h4>规则说明</h4>
      <ul>
        <li><strong>触发条件</strong>：...</li>
        <li><strong>交互反馈</strong>：...</li>
        <li><strong>异常处理</strong>：...</li>
      </ul>
    </div>
    <!-- 右侧：原型沙盒 -->
    <div style="flex: 0 0 auto; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden;">
      <div style="background: #f3f4f6; padding: 8px 12px; font-size: 12px; color: #6b7280;">
        📱 专注模式 · 已锁定无关功能
      </div>
      <iframe
        src="prototype.html?focus=[feature_id]#[page]"
        style="width: 100%; height: 600px; border: none;"
        sandbox="allow-scripts allow-same-origin">
      </iframe>
    </div>
  </div>
</div>
```

#### 4.2 HTML PRD 结构

```
1. 项目信息 + 版本记录
2. 需求背景
3. 需求目标（目标类型 / 描述 / 衡量指标 / 目标值）
4. 用户与使用场景（User Journey Map）
5. 功能清单（骨架与优先级）
6. 详细方案（带沙盒切片 ← 核心）
7. 业务流程图（Mermaid）
8. 异常与边界处理
9. 数据追踪与埋点
10. 未来演进规划
```

页面必须有：悬浮 TOC 导航、版本切换器（预留）、清晰的字体层级与间距。

### Step 5: 落盘与检查

- [ ] 原型文件存入 `workspaces/<workspace>/exports/vN/prototype.html`
- [ ] [可选] HTML PRD 存入 `workspaces/<workspace>/exports/vN/`
- [ ] 执行 `pmagent link --project <project>` 建立双向链接
- [ ] 回显落地路径确认

## 交付检查清单

- [ ] 单文件 HTML，浏览器直接打开即可运行
- [ ] Hash 路由：`#page-name` 切换页面正常
- [ ] Focus Mode：`?focus=xxx` 正确锁定无关功能
- [ ] 关键交互状态覆盖（空状态、加载中、错误态）
- [ ] 模拟数据贴近真实
- [ ] 色彩/间距/字体层级一致
- [ ] [如有 HTML PRD] iframe 切片路径正确，sandbox 属性已加

## 参考

- 原始参考：[Agile-PM-Workflow](https://github.com/chyxin071-sys/Agile-PM-Workflow) — PRD 与原型双向联动、iframe 沙盒切片、Focus Mode
- frontend-design skill（如已安装）可用于提升原型设计质量



## Step Contract (Protocol Boundary)

- **Reads**: Current workspace `Requirement.md`, `workspace-summary.md`, and the research/context/decisions/PRD files explicitly required by this step.
- **Writes**: This step's target artifact directory. If current state, conclusions, risks, or delivery status changes, update `workspace-summary.md`.
- **May mutate**: Files in the current workspace that are directly owned by this step.
- **Must not mutate**: Unrelated project/workspace files; PRD canonical content or project/global memory without user confirmation.
- **Required user confirmation**: Scope, risks, success metrics, PRD changes, project-level sync, and global memory deposition.
- **Handoff**: End by stating downstream input artifacts, confirmed conclusions, open questions, and conclusions downstream steps must not re-litigate.
