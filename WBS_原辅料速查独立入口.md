# WBS：原辅料速查独立入口（独立于对话框）

> 目标：把已上线的 `excipient_basic_info_tool` 包装成一个**独立入口**——用户只需输入名称，即返回速查结果，**不经过对话框 / 不经过 agent 规划**。
> 约束：不改动既有 30 个工具与已有 `/api/chat`；仅**新增**后端端点 + 前端面板；复用已完成并验收的速查工具。

---

## 阶段1：设计 + 评审（本文档）
**入口形态**
- 后端新增专属端点 `POST /api/excipient/lookup`，**直接调用** `excipient_basic_info_tool(name)`，**绕过 agent 规划**（无 thinking / 选工具环节）。
- 前端新增独立「速查」面板（与对话框平级，不混入对话上下文）。

**契约设计**
- 请求：`POST /api/excipient/lookup`，body `{"name": "乳糖"}`（name 为空 → 400）。
- 响应（结构化，便于前端渲染）：
  ```json
  {
    "ok": true,
    "content": "【实体解析与CAS验证】...【FDA IIG（置信度 100）】...",
    "entity": {"query":"乳糖","canonical":"Lactose","product_type":"药用辅料","cas":"63-42-3"},
    "citations": [{"title":"...","url":"...","source":"fda_iig"}]
  }
  ```
- 内容来源：工具本体返回值已含 `【实体解析与CAS验证】` 章节与 `__citations__:JSON` 尾段；端点负责把 `__citations__` 解析为 `citations` 数组，并把实体章节解析为 `entity`。

**复用与隔离**
- 工具本体（excipient_basic_info.py）一行不改。
- 端点只 `import` 该工具函数，错误隔离沿用工具内部的 try/超时；端点再加一层外层 try，保证 500 不崩溃。

**验收标准（阶段1）**
- 文档评审通过：入口形态、契约、隔离边界明确。

---

## 阶段2：后端独立端点
- 在 `backend/main.py` 新增 `POST /api/excipient/lookup`。
- 逻辑：`name` 校验 → `await excipient_basic_info_tool(name)` → 解析返回值（拆分 `content` 与 citations / entity）→ 返回结构化 JSON。
- 异常：工具异常/超时 → `ok:false` + 友好 message，HTTP 200（不抛 500）。
- **不改动** `/api/chat` 与其它任何路由。

**验收标准（阶段2）**
- 端点存在且返回结构化 JSON；`name` 为空返回 400。

---

## 阶段3：前端速查面板
- 新增独立组件（如 `src/SpeedLookup.tsx`），与现有 Chat 组件平级（独立页签/路由，不共享对话框 state）。
- UI：单一名称输入框 + 「速查」按钮 + 结果区（渲染置信度标签、citations 可点链接、实体解析信息）。
- 调用 `POST /api/excipient/lookup`（走 Vite `/api` 代理）。
- **不引入新依赖**；不改动 Chat 组件逻辑。

**验收标准（阶段3）**
- 面板独立可用；输入「乳糖」→ 展示速查结果与溯源链接。

---

## 阶段4：边界与错误隔离
- 空/超长输入 → 前端禁用按钮或后端 400。
- 工具异常/超时 → 端点返回 `ok:false`，前端展示错误态。
- 与 `/api/chat` 互不干扰（独立入口、独立 state）。

**验收标准（阶段4）**
- 异常路径有友好反馈，不影响其它功能。

---

## 阶段5：全链路自审
- 代码审查：是否改动现有 30 工具？→ 否；是否引入新依赖？→ 否。
- 端点是否条件安全（异常不向上抛）？→ 是。
- 前端是否与对话框解耦？→ 是。

**验收标准（阶段5）**
- 自审清单全绿。

---

## 阶段6：端到端测试
- HTTP 真实调用：`POST /api/excipient/lookup {"name":"乳糖"}` → 断言 `content` 含 `C12H22O11`、`63-42-3`、`FDA IIG`，且响应**不含** agent thinking 字段（证明绕过规划）。
- 前端面板验收：在 `5173` 界面输入名称，确认结果渲染正确、citations 可点。

**验收标准（阶段6）**
- HTTP 断言全中；面板人工验收通过。

---

## 阶段7：启动服务验收 + 待用户验收后提交
- 拉起前后端，用户在界面验收独立入口。
- 先提交 GitHub（代码完备），等用户验收确认功能。

**验收标准（阶段7）**
- 用户在界面完成验收；代码待提交状态干净（仅新增文件 + 端点增量）。

---

## 🆕 阶段8：全 19 源扩展（jiansuo3 内核完整迁移）

> 原速查工具仅接入 12 源（PubChem/Wikipedia/EMA/FAERS/UNII/DrugBank/FDA/DailyMed/PubMed/ClinicalTrials/IIG/Espacenet），
> jiansuo3 内核共 19 个数据源，缺失 7 个——本次补齐。

### 8.1 后端工具层：`excipient_basic_info_tool` 重造

**新增导入（复用已有独立工具的内部函数）**
- `from tools.sources.cde import _search_cde` — 中国药品注册（CDE 辅料登记/API 备案/参比制剂/审评进度）
- `from tools.sources.pmda import _search_pmda` — 日本审评信息（含日本药典 PMDE）
- `from tools.sources.chembl import _search_chembl` — 化合物生物活性/分子靶点/ADMET
- `from tools.sources.cnipa import _search_cnipa` — 中国专利检索（CNIPA + Google Patents 批查）

**新建内置函数（无需额外依赖）**
- `_search_drugscom(query)` — Drugs.com 药品信息（site:drugs.com anysearch 搜索，仅原料药）
- `_search_yaozhi(query)` — 药智网搜索（site:yaozh.com anysearch 搜索，MCP 不可用时兜底）

**CONFIDENCE 新增**
```
cde: 80, pmda: 80, chembl: 95, cnipa: 70, drugscom: 80, yaozhi: 70
```

**SOURCE_FUNCS 新增 6 项**（12 → 18 源，+ anysearch_fallback 兜底 = 19）

**路由更新**
- `EXCIPIENT_ONLY = {"fda_iig"}` — 辅料专属
- `API_ONLY = {"clinicaltrials", "drugscom"}` — 原料药专属
- 通用源 16 项并行；按产品类型确定性追加

### 8.2 E2E 验收结果

| 场景 | 状态 | 响应 | citations | 命中源 | 路由正确 |
|------|------|------|-----------|--------|----------|
| 乳糖（辅料） | 200 OK | 6,855B | 5 | PubChem, UNII, IIG, PubMed, ChEMBL | ✅ IIG 命中, 无 Drugs.com |
| 阿可替尼（API） | 200 OK | 4,195B | 5 | PubChem, UNII, PubMed, ClinicalTrials, ChEMBL | ✅ ClinicalTrials/Drugs.com 命中, 无 IIG |

**路由隔离验证**：辅料 → 自动启用 IIG，禁用 Drugs.com；原料药 → 自动启用 ClinicalTrials + Drugs.com，禁用 IIG。

### 8.3 变更清单

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `backend/tools/sources/excipient_basic_info.py` | ~80 行修改 | +4 import, +2 内置函数, CONFIDENCE/SOURCE_FUNCS/路由全部更新, 描述/错误消息更新 |
| `backend/main.py`（不变） | 0 | 端点 `POST /api/excipient/lookup` 无需修改——工具导入通过 `tools/__init__.py` 注册表 |
| `frontend/`（不变） | 0 | 前端无需修改——响应 schema 不变 |
| `WBS_*`（本文档） | +60 行 | 阶段8 设计文档 + E2E 结果 |

### 8.4 药智 MCP 说明
jiansuo3 中药智网有独立 MCP 客户端（9 子工具：药品注册/上市/医保/集采/医院销售等），当前后端无该 MCP 客户端，
以 `site:yaozh.com` anysearch 搜索作为兜底。后续若接入药智 MCP，将自动升级为 9 子工具并行检索。
