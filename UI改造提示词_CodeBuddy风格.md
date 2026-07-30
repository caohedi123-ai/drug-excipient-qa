# 前端 UI 改造提示词：CodeBuddy 风格

## 任务目标

将现有的"药物原辅料知识问答助手"前端 UI，从当前的"深蓝+金色渐变营销风"改造为 **CodeBuddy 风格的 IDE 工具感设计**。

## 参考对象

CodeBuddy（腾讯 AI 编程助手）的 UI 设计语言，核心特征：
- 深色主题，深蓝灰底色（不是纯黑，不是深蓝）
- 极简克制，零装饰性渐变/glow
- 信息密度高，紧凑排版
- 线性图标，细线条
- 状态用小圆点+文字指示
- 整体像 IDE/开发工具，不像营销页

## 设计语言定义

### 色彩系统

**替换整个 brand + gold 色板**，改用 CodeBuddy 风格的单色系：

```javascript
// tailwind.config.js 色板替换
colors: {
  // 主色：深蓝灰（CodeBuddy 底色）
  bg: {
    0: '#0d1117',      // 最深底（主背景）
    1: '#161b22',      // 次级底（侧边栏、卡片）
    2: '#1c2128',      // 输入框、hover 态
    3: '#21262d',      // 边框、分割线
  },
  // 文字色
  text: {
    primary: '#e6edf3',     // 主文字
    secondary: '#8b949e',   // 次级文字
    tertiary: '#6e7681',    // 辅助文字、placeholder
    muted: '#484f58',       // 禁用态
  },
  // 强调色（唯一强调色，替代金色）
  accent: {
    DEFAULT: '#58a6ff',     // 链接、选中态、按钮
    hover: '#79c0ff',       // hover
    muted: '#1f6feb33',     // 背景态（选中行、tag背景）
  },
  // 状态色
  success: '#3fb950',
  warning: '#d29922',
  error: '#f85149',
}
```

**铁律**：
- ❌ 删除所有 gold 色（金色渐变是"丑"的根源）
- ❌ 删除所有 gradient（渐变背景、渐变文字、渐变边框）
- ❌ 删除所有 glow/shadow 发光效果
- ❌ 删除 backdrop-blur 毛玻璃效果
- ✅ 用纯色 + 微透明度区分层级
- ✅ 唯一强调色是 `accent`（浅蓝），用于链接、选中态、主按钮

### 排版

```css
/* 字体 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', Helvetica, Arial, sans-serif;

/* 字号体系（紧凑） */
--text-xs: 12px;    /* 辅助文字、时间戳 */
--text-sm: 13px;    /* 正文、列表项 */
--text-base: 14px;  /* 主内容 */
--text-lg: 16px;    /* 标题 */

/* 行高 */
--leading-tight: 1.4;
--leading-normal: 1.6;
```

### 间距与圆角

```css
/* 圆角：统一 6px，不要大圆角 */
--radius-sm: 4px;   /* tag、小按钮 */
--radius-md: 6px;   /* 卡片、输入框 */
--radius-lg: 8px;   /* 大容器 */

/* 间距：紧凑 */
--gap-xs: 4px;
--gap-sm: 8px;
--gap-md: 12px;
--gap-lg: 16px;
```

### 边框

```css
/* 所有边框统一：1px solid，低对比度 */
border: 1px solid #21262d;  /* bg-3 */

/* 选中态/活跃态 */
border: 1px solid #58a6ff;  /* accent */

/* ❌ 删除 gradient-border 伪元素 */
/* ❌ 删除所有 1px 渐变边框 */
```

### 阴影

```css
/* 几乎不用阴影，最多用于浮层 */
box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);  /* 仅 dropdown/popover */

/* ❌ 删除所有 shadow-lg、shadow-gold、shadow-brand */
/* ❌ 删除所有 box-shadow 发光效果 */
```

---

## 组件改造规范

### 1. 全局背景 (index.css body)

**当前问题**：径向渐变背景（蓝色+金色光晕）

**改为**：
```css
body {
  background-color: #0d1117;  /* 纯色，无渐变 */
  color: #e6edf3;
  /* 删除 background-image 的 radial-gradient */
  /* 删除 background-attachment: fixed */
}
```

### 2. 侧边栏 (Sidebar.tsx)

**参考 CodeBuddy 左侧栏**：
- 宽度：260px（展开）/ 48px（收起）
- 背景：`#161b22`（比主背景浅一档）
- 右边框：`1px solid #21262d`
- 无渐变、无发光

**结构**：
```
┌─────────────────────┐
│ 🔍 搜索任务     ⚙️  │  ← 搜索栏 + 设置按钮
├─────────────────────┤
│ + 新建对话          │  ← 主按钮，accent 色边框
├─────────────────────┤
│ 📁 药物原辅料知识... │  ← 文件夹分组
│   • 精致芝麻油作为... │  ← 选中项：bg accent-muted + 左边框 2px accent
│   • 布洛芬片的辅料... │  ← 未选中：hover 变 bg-2
│   • 莫洛替尼的临床... │
│ 📁 jiansuo2         │
│   • 检索系统优化...   │
├─────────────────────┤
│ 🟢 秋水             │  ← 底部用户信息
└─────────────────────┘
```

**具体改动**：
- 删除侧边栏 header 的渐变 logo 方块
- 删除底部 "v2.0" 小绿点装饰
- 历史列表项：选中态改为 `background: #1f6feb33; border-left: 2px solid #58a6ff;`
- 新建对话按钮：`border: 1px solid #58a6ff; color: #58a6ff; background: transparent;` hover 时 `background: #1f6feb22;`
- 文件夹标题：`color: #8b949e; font-size: 12px; text-transform: uppercase;`

### 3. 顶部 Header (ChatContainer.tsx)

**当前问题**：header-glow 发光底线、渐变 logo、金色副标题

**改为**：
```
┌──────────────────────────────────────────────┐
│  药物原辅料知识问答          [停止] [🗑️]     │
│  ─────────────────────────────────────────── │  ← 1px solid #21262d 分割线
└──────────────────────────────────────────────┘
```

- 高度：48px，紧凑
- 背景：与主背景同色 `#0d1117`
- 底边框：`1px solid #21262d`（替代 header-glow）
- 标题：`color: #e6edf3; font-size: 14px; font-weight: 600;`
- 副标题：`color: #8b949e; font-size: 12px;`
- Logo：删除渐变方块，用一个简单的 SVG 图标 + `color: #58a6ff;`
- 停止按钮：`border: 1px solid #f85149; color: #f85149; background: transparent;`
- 清空按钮：`color: #8b949e;` hover `color: #e6edf3;`

### 4. 消息气泡 (MessageBubble.tsx)

**当前问题**：用户消息是金色渐变背景 + 金色阴影，太抢眼

**改为**：

**用户消息**：
```css
/* 右对齐，浅灰背景，无渐变 */
.msg-user {
  background-color: #1f6feb33;  /* accent muted */
  border: 1px solid #1f6feb44;
  border-radius: 6px;
  color: #e6edf3;
  padding: 8px 12px;
  max-width: 70%;
  margin-left: auto;
  /* ❌ 删除 gradient */
  /* ❌ 删除 box-shadow */
  /* ❌ 删除 border-radius: 1rem（大圆角） */
}
```

**AI 消息**：
```css
/* 左对齐，无背景或极浅背景 */
.msg-assistant {
  background-color: transparent;  /* 或 #161b22 */
  border: none;  /* 或 1px solid #21262d */
  border-radius: 6px;
  color: #e6edf3;
  padding: 8px 0;  /* 无背景时不需要 padding */
  max-width: 100%;  /* 占满宽度 */
  /* ❌ 删除 border-radius: 1rem */
  /* ❌ 删除 background-color: rgba(15, 44, 102, 0.6) */
}
```

**AI 头像**：
- 删除渐变方块
- 改为：`width: 24px; height: 24px; border-radius: 50%; background: #21262d;` 内嵌一个 `color: #58a6ff;` 的小图标

**流式光标**：
- 删除金色闪烁条
- 改为：`width: 2px; height: 16px; background: #58a6ff; animation: blink 1s step-end infinite;`

### 5. 思考过程 (ThinkingProcess.tsx)

**当前问题**：glass-card-light 毛玻璃、金色图标

**改为**：
```
▸ 思考过程 (3 步)
  ✓ 实体识别: sesame oil
  ✓ 意图分类: excipient_info  
  ● 检索中: 调用 5 个数据源...
```

- 容器：`background: #161b22; border: 1px solid #21262d; border-radius: 6px;`
- Header：`color: #8b949e; font-size: 12px;`
- 步骤图标：
  - 完成：`color: #3fb950;`（绿色 ✓）
  - 进行中：`color: #58a6ff;`（蓝色脉冲点）
  - 失败：`color: #f85149;`（红色 ✗）
  - 等待：`color: #484f58;`（灰色）
- 步骤文字：`color: #8b949e; font-size: 12px;`
- ❌ 删除 gold-400 图标色
- ❌ 删除 glass-card-light 毛玻璃

### 6. 参考来源 (ReferenceList.tsx)

**当前问题**：glass-card-light、渐变图标背景

**改为**：
```
▸ 参考来源 (3 条)
  ┌──────────────────────────────────────┐
  │ 📄 DailyMed    [FDA]    85%         │
  │    ProBliva Psoriasis Shampoo...     │
  └──────────────────────────────────────┘
```

- 容器：同思考过程样式
- 来源卡片：`background: #0d1117; border: 1px solid #21262d; border-radius: 4px;`
- 来源图标：`width: 20px; height: 20px; background: #21262d; border-radius: 4px;`
- 来源标签（如 "FDA"）：`background: #1f6feb33; color: #58a6ff; padding: 2px 6px; border-radius: 4px; font-size: 11px;`
- 相关度百分比：`color: #8b949e; font-size: 11px;`
- ❌ 删除图标区域的渐变背景

### 7. 输入框 (ChatInput.tsx)

**当前问题**：glass-card + gradient-border + 金色发送按钮

**改为**：
```
┌──────────────────────────────────────────────┐
│ 输入您的药物原辅料问题...              [→]   │
│ Enter 发送 · Shift+Enter 换行                │
└──────────────────────────────────────────────┘
```

- 容器：`background: #161b22; border: 1px solid #21262d; border-radius: 6px;`
- Focus 态：`border-color: #58a6ff;`
- 输入框文字：`color: #e6edf3; placeholder: #484f58;`
- 发送按钮：
  - 默认（有内容）：`background: #58a6ff; color: #0d1117; border-radius: 4px;`
  - 禁用（无内容）：`background: #21262d; color: #484f58;`
  - ❌ 删除金色渐变
  - ❌ 删除 shadow-lg shadow-gold
- 底部提示文字：`color: #484f58; font-size: 11px;`

### 8. 空状态 (Empty State)

**当前问题**：大图标 + 渐变边框方块 + 金色图标

**改为**：
```
         💊
  药物原辅料知识问答助手
  
  基于 FDA IIG、UNII、DrugBank 等权威数据源，
  提供药物原辅料的智能检索与知识问答服务。

  [莫洛替尼的临床试验信息]  [布洛芬片的辅料组成]
  [FDA IIG 数据库查询方法]  [对乙酰氨基酚的UNII编号]
```

- 图标：简单的 SVG，`color: #58a6ff;` 或 `#8b949e;`
- 标题：`color: #e6edf3; font-size: 16px; font-weight: 600;`
- 描述：`color: #8b949e; font-size: 13px;`
- 快捷问题按钮：
  - `background: #161b22; border: 1px solid #21262d; color: #8b949e;`
  - hover：`border-color: #58a6ff; color: #58a6ff;`
  - ❌ 删除 bg-brand-800/40
  - ❌ 删除 border-brand-700/30

### 9. 系统消息 (msg-system)

**改为**：
```css
.msg-system {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 6px;
  color: #8b949e;
  font-size: 12px;
  padding: 6px 12px;
  text-align: center;
  /* ❌ 删除 gold-400 图标 */
}
```

---

## 需要删除的 CSS 类（index.css）

以下类/效果必须**完全删除**：

1. `.glass-card` — 毛玻璃效果
2. `.glass-card-light` — 毛玻璃效果
3. `.text-gradient` — 金色渐变文字
4. `.text-gradient-blue` — 蓝色渐变文字
5. `.gradient-border` — 渐变边框伪元素
6. `.header-glow` — 头部发光底线
7. `.btn-gold` — 金色按钮
8. `box-shadow: ... shadow-gold ...` — 所有金色阴影
9. `background-image: linear-gradient(...)` — 所有渐变背景
10. `backdrop-filter: blur(...)` — 所有毛玻璃
11. `radial-gradient(...)` — body 背景光晕
12. `.pulse-dot` 的金色背景色 → 改为 `#58a6ff`

## 需要保留的 CSS 类

1. `.btn-primary` → 改色为 accent 蓝
2. `.btn-danger` → 改色为 error 红
3. `.thinking-step` → 改色为灰/蓝/绿/红
4. `scrollbar` 样式 → 改色为 `#21262d`
5. 动画 `fade-in`、`slide-up` → 保留，但缩短时长到 0.2s

---

## 改造顺序

1. **tailwind.config.js** — 替换色板（brand+gold → bg+text+accent）
2. **index.css** — 删除所有渐变/毛玻璃/glow，重写组件类
3. **App.tsx** — 更新背景色引用
4. **Sidebar.tsx** — 重写样式
5. **ChatContainer.tsx** — 重写 header + 空状态 + 消息列表
6. **MessageBubble.tsx** — 重写气泡样式
7. **ChatInput.tsx** — 重写输入框
8. **ThinkingProcess.tsx** — 重写步骤样式
9. **ReferenceList.tsx** — 重写来源卡片

## 验收标准

改造完成后，界面应该：
- ✅ 看起来像一个 IDE/开发工具，不像营销页
- ✅ 没有任何金色元素
- ✅ 没有任何渐变（背景、文字、边框）
- ✅ 没有任何发光/毛玻璃效果
- ✅ 信息密度高，排版紧凑
- ✅ 只有一个强调色（浅蓝 #58a6ff）
- ✅ 深色底，低对比度边框
- ✅ 状态指示清晰（绿=完成，蓝=进行中，红=失败，灰=等待）

## 参考截图

CodeBuddy 界面特征（从截图提取）：
- 主背景：深灰偏蓝（约 #0d1117）
- 侧边栏：稍浅一档（约 #161b22）
- 卡片/输入框：再浅一档（约 #1c2128）
- 边框：低对比度（约 #21262d）
- 选中态：蓝色左边框 + 蓝色半透明背景
- 文字：主文字亮白（#e6edf3），次级灰（#8b949e）
- 强调色：浅蓝（#58a6ff）
- 按钮：线框风格（透明底 + 色边框）
- 整体感觉：安静、克制、专业
