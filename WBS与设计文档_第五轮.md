# 第五轮需求 — WBS 分解与设计文档

> 范围：仅本地更新。流程：同步 GitHub(已完成) → WBS → 设计 → 子agent评审 → 开发 → 测试 → E2E → WBS 更新 → 本地服务启动。

## 一、需求清单（用户原话拆解）

| # | 需求 | 类型 |
|---|------|------|
| 1 | 点历史对话后再点"新问答"，对话框仍显示历史对话内容 | Bug 修复 |
| 2 | 速查历史显示"几分钟前"，隔天后显示日期 | 功能增强 |
| 3 | DeepSeek / Tavily / AnySearch 三个 API 提供配置入口，默认值作默认，不明文显示（遮挡部分字符） | 功能新增 |
| 4 | 影响任务时长的参数（最大轮数、8000~20万字符预算等）做配置入口，简化为 flash~pro 5 档位，对话框旁直接选择；配置里是自定义详细配置；默认最长时间（质量优先），flash 代表速度优先 | 功能新增 |

## 二、WBS 分解

```
M1 同步 GitHub                                    [✅ 已完成]
M2 设计（本文档） + 子agent 评审                   [✅ 已完成]
M3 开发                                              [✅ 已完成]
  M3.1 [Bug] 修复会话切换残留历史内容 (ChatContainer)     ✅
  M3.2 [前端] 速查时间相对格式化 (Sidebar + time.ts)       ✅
  M3.3 [后端] API 配置存取：/api/settings GET/PUT + 掩码 + 持久化 ✅
  M3.4 [前端] 设置面板（3 个 API 输入，遮挡明文）           ✅ SettingsModal.tsx
  M3.5 [后端] 检索档位定义 + /api/chat 接收 tier + 请求级参数覆盖（ContextVar） ✅
  M3.6 [前端] 档位选择器（对话框旁 5 档下拉）+ api.ts 传参  ✅ TierSelector.tsx + ChatContainer 接入
  M3.7 [前端] 设置面板内自定义详细配置表单                  ✅ SettingsModal 检索面板
M4 测试                                              [✅ 已完成]
  M4.1 后端脚本验证（settings 接口、档位映射、掩码、持久化）✅ 全部通过
  M4.2 前端 tsc --noEmit + vite build                    ✅ 无错误
M5 E2E 验证（本地起服务，4 项需求链路验证）          [✅ 已完成]
  - tier=flash SSE 聊天 200 + [DONE]，档位注入链路正常
  - /api/settings GET 掩码正确、PUT 保存/落盘/恢复正常
  - 前端代理登录连通、Vite dev server 已启动
M6 WBS 文档更新 + 本地服务启动                      [✅ 已完成]
  - 后端 127.0.0.1:18082 / 前端 127.0.0.1:15173 已启动
```

## 三、需求 1 — 会话切换残留历史内容（Bug）

### 3.1 根因（已定位）

`frontend/src/components/ChatContainer.tsx` `useEffect`（116-236 行）：

- 点击"新问答"时 App 创建新会话 B 并 `setActiveId(B.id)`，`conversation` prop 变为 B。
- useEffect 触发：`oldId = A.id`（有值），`newId = B.id`（未缓存）。
- 走到 else 分支，判定 `hasLocal = msgsRef.current.length > 0` → **此时 msgsRef 中仍是历史会话 A 的消息** → 判定为"本地新消息" → 跳过清空。
- 随后 `fetchConversationMessages(B)` 返回空数组（新会话无历史）→ 因 `backendMsgs.length === 0` 不写入任何内容。
- 结果：messages 保持 A 的历史内容，B 对话框显示 A 的残留消息。

### 3.2 修复方案

将"是否保留本地消息"的判定与**旧会话归属**绑定：

```
hasLocal = (oldId === null) && msgsRef.current.length > 0
```

- `oldId === null`：从"无会话状态"首次进入（用户首屏直接输入提问创建会话），此时 msgsRef 中正是本会话刚发的用户消息 → 保留。
- `oldId !== null`：从历史会话 A 切换到 B → msgsRef 中必定是 A 的残留 → 清空。

同时补充：`newId === null`（删除当前会话后 activeId 置空）时也应清空显示状态，避免删除后仍残留。

修改点（`ChatContainer.tsx` useEffect 144-154 行区域）：

```ts
} else {
  // 未缓存 —— 从后端加载历史消息
  // 修复：仅当「此前无旧会话」且本地确有消息（首屏直接提问创建）时才保留，
  // 否则 msgsRef 中是旧会话残留，必须清空
  const hasLocal = oldId === null && msgsRef.current.length > 0
  if (!hasLocal) {
    setMessages([])
    setStreamingContent('')
    setThinkingSteps([])
    setReferences([])
    setError(null)
  }
  ...
}
// newId 为 null（删除会话等）时清空显示
else {
  setMessages([])
  setStreamingContent('')
  setThinkingSteps([])
  setReferences([])
  setError(null)
  setIsStreaming(false)
}
```

同时确认 `handleSend` 中创建新会话的时序：先 `setMessages` 添加用户消息、再 `onUpdate(newConv)` 更新 conversation，保证 useEffect 触发时 msgsRef 已包含本会话用户消息（React 批处理下 render 后 useEffect 可见）。

## 四、需求 2 — 速查历史相对时间

### 4.1 现状

`frontend/src/components/Sidebar.tsx` 112-114 行：

```tsx
<span className="text-[10px] text-[#484f58]">
  {item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : ''}
</span>
```

仅显示"MM月DD日"，无"几分钟前"。

### 4.2 方案

新建工具 `frontend/src/lib/time.ts`：

```ts
export function formatRelativeTime(iso: string | undefined | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  const d = new Date(t); const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return `${Math.floor(diff / 3_600_000)}小时前`
  // 隔天：显示日期
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
```

Sidebar 速查历史引用该函数替换 `toLocaleDateString` 调用。

## 五、需求 3 — 3 个 API 配置入口

### 5.1 后端

新增配置覆盖层，**不修改现有 pydantic settings 结构**，避免影响 nodes 模块级 `settings.xxx` 读取：

- 新文件 `backend/settings_service.py`：
  - `USER_SETTINGS_FILE = backend/user_settings.json`（与 .env 同目录），存 JSON：`{"deepseek_api_key": "...", "tavily_api_key": "...", "anysearch_api_key": "...", "retrieval": {...自定义档位参数...}}`
  - 启动时 `load_overrides()`：若文件存在，将其中 key 直接赋值到 settings 单例（`settings.deepseek_api_key = x`），实现"默认值作为默认、可覆盖"。
  - `get_masked(key)`：返回掩码串 `sk-xxxx****`（前 4 后 4，长度 <8 全掩码）。
  - `save_overrides(payload)`：校验 key 名合法（白名单），非空则写文件 + 更新 settings 单例；返回更新后的掩码视图。
- `backend/main.py` 新增端点：
  - `GET /api/settings` → `{ api_keys: { deepseek: {masked, configured}, tavily: {...}, anysearch: {...} }, retrieval: {...当前生效自定义参数...} }`
  - `PUT /api/settings` → body `{ deepseek_api_key?, tavily_api_key?, anysearch_api_key?, retrieval? }`；空字符串 = 不改动；更新后持久化。
- 掩码逻辑：`value[:4] + '****' + value[-4:]`（仅当长度 ≥ 8）；无配置时 masked 为 `''`、configured=false。

### 5.2 前端

- 设置面板组件 `frontend/src/components/SettingsModal.tsx`：
  - 入口：Sidebar 底部/Header 齿轮按钮（新增）。
  - 3 个输入框：`type="password"`，placeholder 显示掩码值（如 `sk-xxx****abcd`），明文不落 DOM（value 用空字符串 + placeholder 提示），保存时仅发送用户新输入的字符，留空表示不改。
  - 保存 → `PUT /api/settings` → 刷新 GET 掩码状态。
- 附带在设置面板内提供**检索自定义详细配置**表单（需求 4 的"配置里是自定义的详细配置"）。

## 六、需求 4 — 检索档位（flash ~ pro 5 档）

### 6.1 档位定义

新增 `backend/agent/tiers.py`，5 档映射全部时长相关参数：

| 档位 | max_retrieval_rounds | retrieval_max_chars_per_source | retrieval_max_total_chars | retrieval_max_store_chars | history_inject_rounds | history_compress_rounds | history_max_total_chars | history_smart_truncate_chars | 说明 |
|------|-----|------|------|------|------|------|------|------|------|
| flash | 1 | 2000 | 40000 | 4000 | 0 | 8 | 1500 | 80 | 速度优先（最快） |
| fast  | 2 | 4000 | 80000  | 6000 | 1 | 6 | 3000 | 120 | 快速 |
| balanced | 3 | 8000 | 200000 | 12000 | 2 | 4 | 6000 | 200 | 均衡（=当前默认值） |
| quality | 4 | 10000 | 300000 | 16000 | 2 | 3 | 8000 | 260 | 质量优先 |
| pro   | 5 | 12000 | 400000 | 20000 | 3 | 3 | 10000 | 320 | 质量优先（默认，最长时间） |

> 默认档位 **pro**（用户要求"默认最长时间，质量优先"）。flash 代表速度优先。
> balanced 与当前 `.env` 默认值完全一致，作为回归基准。

### 6.2 请求级参数覆盖（ContextVar 方案）

**关键约束**：系统已实现多会话并发（applyConvState），**不能**用全局 settings 覆盖（会串会话）。采用请求级 ContextVar：

- 新文件 `backend/agent/runtime_cfg.py`：

```python
from contextvars import ContextVar
_runtime = ContextVar("retrieval_runtime", default=None)  # dict or None

def set_runtime(overrides: dict | None):
    return _runtime.set(overrides)

def reset_runtime(token):
    _runtime.reset(token)

def get_param(name: str, default):
    """优先读取请求级覆盖，否则回退默认值"""
    ov = _runtime.get()
    if ov and name in ov:
        return ov[name]
    return default
```

- `/api/chat` 请求体增加 `tier: str = "pro"` 与 `custom_tier: dict | None`（当 tier="custom" 时携带前端自定义参数）。
- 后端解析：`tier` ∈ {flash, fast, balanced, quality, pro} → 使用预设映射；`tier="custom"` → 使用 settings_service 中保存的自定义 retrieval 参数（或请求体 custom_tier）。
- 解析结果作为 `overrides`，在调用 graph 前 `set_runtime(overrides)`，`finally` 中 `reset_runtime(token)`。
- `recursion_limit = max_retrieval_rounds * 6 + 12` 也改为基于 overrides 中的轮数计算。

### 6.3 nodes 改造（将直接 settings 读取改为 get_param）

涉及参数读取点（已 grep 确认），统一改为 `get_param('参数名', settings.参数名)`：

- `agent/nodes/decide.py:27` — max_retrieval_rounds
- `agent/nodes/retrieve.py:107,131` — retrieval_max_store_chars
- `agent/nodes/final_search.py:116` — retrieval_max_store_chars
- `agent/nodes/evaluate.py:81,83,90-91,113,277,281,289-290` — history_inject_rounds / history_smart_truncate_chars / retrieval_max_total_chars / retrieval_max_chars_per_source
- `agent/nodes/understand.py:126,133,143` — history_inject_rounds / history_smart_truncate_chars / history_max_total_chars
- `agent/graph.py:96` — history_compress_rounds
- `main.py:225` — recursion_limit

### 6.4 前端

- `frontend/src/lib/api.ts`：`sendChatMessage` 增加 `tier?: string` 参数，随请求体发送（Signal 上仅透传，不参与缓存键，避免并发串台）。
- `frontend/src/components/ChatInput.tsx` 或 ChatContainer 输入区：新增档位下拉（5 档 + custom），默认 **pro**，本地 state（可按会话记忆，简化：全局组件 state 默认 pro）。
- 选择 custom 时展开（或跳转设置面板）自定义参数编辑（与设置面板 retrieval 表单共用组件）。

## 七、接口与数据流总结

```
前端 SettingsModal ──GET/PUT──> /api/settings ──> settings_service (user_settings.json + settings单例覆盖)
前端 档位选择器 ──tier──> sendChatMessage ──> POST /api/chat {tier, custom_tier}
后端 /api/chat ──解析档位──> overrides dict ──set_runtime(ContextVar)──> graph nodes get_param 读取
```

## 八、测试与验收要点

1. Bug：A 会话发消息 → 点 B 历史 → 点"新问答" → 对话框为空（无 A 残留）。
2. 速查：本地插入带 created_at 的历史，今天显示"X分钟前/X小时前"，隔天显示日期。
3. 设置：GET 掩码正确；PUT 后 GET 掩码变化；重启服务后仍生效（持久化文件）。
4. 档位：flash 返回快、pro 最慢且质量高；并发两会话用不同档位互不干扰（ContextVar 隔离）。
5. 回归：balanced 档参数与现状完全一致，默认 pro 不影响既有功能。

## 九、风险与注意事项

- pydantic settings 单例被模块级引用：覆盖只应发生在**进程启动加载**与 **PUT /api/settings** 时，避免请求中直接改全局 settings（并发冲突）。
- `user_settings.json` 需加入 .gitignore（含密钥），不提交仓库。
- API key 掩码：仅前端展示层遮挡，传输与落盘为明文（本地单机部署可接受；如需加密后续可加）。
- 档位选择器状态不与具体会话绑定，全局记住用户最近选择（简化实现）。

## 十、第五轮实际完成记录（2026-08-04）

### 10.1 实现明细

| 需求 | 文件 | 要点 |
|------|------|------|
| Bug 1 | `ChatContainer.tsx` | `hasLocal = oldId === null && msgsRef.length>0`；`newId===null` 分支清空全部显示状态 |
| 需求 2 | `Sidebar.tsx` + 新建 `lib/time.ts` | `<60min` 显示"X分钟前"、同日"X小时前"、隔天"X月X日" |
| 需求 3 | 新建 `settings_service.py`；`main.py` 增 GET/PUT `/api/settings`（`Depends(requires_auth)`）；新建 `SettingsModal.tsx`；`api.ts` 增 `fetchSettings/updateSettings`；`App.tsx` Header 齿轮入口 | 掩码前 4 后 4、长度<8 全 `***`；空串不改动；`user_settings.json` 落盘；启动 `load_overrides()` |
| 需求 4 | 新建 `agent/tiers.py`（5 档 + custom）；新建 `agent/runtime_cfg.py`（ContextVar）；`main.py` ChatRequest 增 `tier/custom_tier`、`resolve_tier`+`set_runtime`+`recursion_limit`；7 个节点 `settings.x` → `get_param('x', settings.x)`；新建 `TierSelector.tsx`；`api.ts` `sendChatMessage` 第五参 `tier`；`ChatContainer` 输入区接入选择器 | 默认 `pro`；`balanced` 与 .env 默认一致作回归基准 |

### 10.2 验证结果（已执行）

- ✅ 后端脚本：档位解析（含 custom/未知回退 pro）、掩码、持久化读写/覆盖/落盘全部通过
- ✅ 前端 `tsc --noEmit` 无错误、`vite build` 成功
- ✅ E2E：`POST /api/chat {tier:"flash"}` 返回 200、含 `[DONE]`、无 error（档位注入全链路正常）
- ✅ E2E：`GET/PUT /api/settings` 掩码正确、PUT 保存后 GET 反映、落盘文件格式正确、测试后已清理残留
- ✅ 前端代理链路：经 Vite(15173)→后端(18082) 登录成功
- ✅ 服务：后端 18082 / 前端 15173 本地已启动

### 10.3 遗留说明

- 前端浏览器手工流程（点历史→新问答清空、设置面板交互、档位切换）建议用户实测确认观感。
- 需求 4 档位默认 pro（最长检索）；custom 档需先在设置面板保存自定义参数。
