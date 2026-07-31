# 迁移 jiansuo3 检索内核 — 可行性判断与 WBS

> 依据：`迁移提示词_jiansuo3检索内核.md`（几天前写，目标不变，但项目已演进）
> 目标（不变）：将 jiansuo3 检索内核的检索**策略**（关键词扩展 + 实体解析 + CAS 验证 + 多数据源并行 + 3 层降级 + 置信度分级 + 产品类型路由）封装为一个「原辅料基本信息速查」工具，错误隔离、可单独禁用，不影响其他工具。

---

## 一、可行性结论

**能做到 ✅**

但原提示词假设的项目结构是「12 个工具 + `ToolNode`/`PHASE1_TOOLS`」，而当前版本已变为 **30 个工具**（`ALL_TOOLS`），且 jiansuo3 内核覆盖的每一个数据源（PubChem / Wikipedia / EMA / FAERS / UNII / DrugBank / FDA / DailyMed / PubMed / ClinicalTrials / FDA IIG / Espacenet）现在都已是独立的 LangChain 工具；另有 `anysearch_engine / tavily_engine / exa_engine` 三套降级引擎；工具注册仍走 `ToolNode` + `get_tool_node()`，并保留 `PHASE1_TOOLS = ALL_TOOLS` 兼容名。

因此原提示词的「复制 jiansuo3 的 TS 内核到 `backend/tools/jiansuo3-core/`，Python 用 `subprocess` 调 `node`」方案已**不再是最优**，且更脆弱。推荐改为**纯 Python 聚合速查工具，复用现有工具与引擎**。

### 与原提示词的关键差异（设计阶段需你拍板）

| 维度 | 路线 A（原提示词） | 路线 B（推荐，适配当前版本） |
|---|---|---|
| 实现 | 复制 jiansuo3 的 `llm.ts`(914行)/`data-sources.ts`(2029行) 等 TS，Python `subprocess` 调 `node` | 新建 Python 工具 `excipient_basic_info_tool`，内部并行调现有 12~14 个相关工具 + 引擎兜底 |
| 依赖 | 需 Node 子进程、需从 jiansuo3 复制 API Key | 纯 Python，复用当前 `.env` 已配的 deepseek/tavily/anysearch |
| 架构契合 | 与当前 Python 工具体系割裂，崩溃隔离靠 subprocess 超时 | 与 30 工具 / 引擎 / agent 图天然一致 |
| 风险 | 跨语言开销、TS 大文件维护、Key 复制、Node 挂起 | 需补建「实体解析+CAS 验证」与「置信度分级」两块 |
| 策略保留 | 直接调用 jiansuo3 函数 | 同等保留六大策略（见下），满足"策略不能丢" |

> 两条路线都满足"策略不能丢"的核心原则；用户评审时二选一。

### 当前已具备 / 仍缺失

- ✅ 已具备：LLM 关键词扩展（`agent/nodes/expand.py`，比 jiansuo3 更强，维度化差异化查询词）；全部数据源工具；3 套降级引擎；错误隔离的导入/运行框架（`try/except` 包裹 + 条件注册）。
- ❌ 仍缺失：**独立的「实体解析 + CAS 验证」**（全文搜索无 `resolve_entity`/`verify_cas`）；**数值化置信度分级**（现有工具返回 `SearchResult` 但未确认带 `confidence` 字段，需在聚合层补足）。

---

## 二、WBS（颗粒度：设计 → 评审 → 开发 → 测试 → 全链路自审 → 端到端测试 → 启动服务）

### 阶段 1：设计（Design）
- 1.1 确定实现路线（A 跨语言 / B 纯 Python 复用），产出《实现路线决策》。
- 1.2 梳理「原辅料基本信息速查」字段清单，**严格对齐 jiansuo3 字段清单**（PubChem/Wikipedia/EMA/FAERS/UNII/DrugBank/FDA/DailyMed/PubMed/ClinicalTrials/FDA IIG/Espacenet），不杜撰字段。
- 1.3 设计工具内部流程：关键词扩展 → 实体解析+CAS 验证 → 产品类型路由 → 多源并行 → 3 层降级 → 聚合去重 + 置信度分级。
- 1.4 设计错误隔离方案：`try/except` 包裹全部、超时控制（`asyncio.wait_for` 60s）、失败返回空/友好提示、可单独禁用（导入失败不阻断其他工具）、不修改全局状态。
- 1.5 确认现有 30 工具是否带数值化 `confidence`；若无，在聚合层定义置信度分级（API=100 / extract=80-90 / 搜索=60-70）。
- 1.6 设计工具 I/O 契约（对齐 `SearchResult` / `Citation`，便于并入 `retrieval_results` 与 `citations`）。
- **产出**：《速查工具设计文档》（流程、字段表、错误隔离、契约）。

### 阶段 2：评审（Review）
- 2.1 评审路线选择（A vs B，重点评估维护性、崩溃隔离、与当前架构契合度）。
- 2.2 逐条核对字段清单完整性且未杜撰（对照 jiansuo3 字段清单）。
- 2.3 评审错误隔离是否达标（崩溃 / 超时 / 异常 / 导入失败 均不影响其他 30 工具）。
- 2.4 评审与现有 agent 图（`decide/retrieve/synthesize`）的衔接：速查工具作为「数据源工具」被 `retrieve` 调用，确认不破坏现有图、不引入回边/死循环。
- 2.5 评审置信度分级与降级策略是否忠实保留 jiansuo3 策略。
- **产出**：《设计评审意见》（含修正项，回到 1.x 修正后进入开发）。

### 阶段 3：开发（Develop）
- 3.1 新建 `backend/tools/sources/excipient_basic_info.py`：`@tool` 装饰的 `excipient_basic_info_tool`。
- 3.2 关键词扩展（复用 `expand` 思路或工具内轻量 LLM 扩展，输出 `englishName` / `casNumber` / `productType`）。
- 3.3 实体解析 + CAS 验证（借鉴 jiansuo3 `llm.ts` 的 `resolveEntity` / `verifyCASNumber`，用 Python + 当前 LLM / PubChem 重写，不信任 LLM 给的 CAS）。
- 3.4 产品类型路由：辅料→启用 `fda_iig_tool`、跳过 `clinicaltrials_tool`；原料药→反之。
- 3.5 多源并行：`asyncio.gather` 并行调 12~14 个现有相关工具（pubchem / drugbank / fda_iig / fda_unii / dailymed / fda_drugs / ema / cde / fda_faers / rxnorm / pubmed / wikipedia / clinicaltrials / espacenet 等）。
- 3.6 接入 3 层降级：各工具自身降级 + 末轮 `anysearch_engine` 兜底（复用现有引擎）。
- 3.7 聚合去重 + 置信度分级（选最高置信度）+ 构造 `SearchResult` 与 `Citations`。
- 3.8 错误隔离：最外层 `try/except`、`asyncio.wait_for(60s)`、全部异常内部捕获返回空/友好提示、不修改全局状态。
- 3.9 注册到 `backend/tools/__init__.py`：`try/except` 导入 + 条件加入 `ALL_TOOLS`（可单独禁用，兼容 `PHASE1_TOOLS`）。
- 3.10 配置确认：`.env` 中 deepseek / tavily / anysearch 键已就位（无需从 jiansuo3 复制）。
- **产出**：可导入、可单独调用的 `excipient_basic_info_tool` + 注册更新。

### 阶段 4：测试（Test）
- 4.1 单元：乳糖（辅料）字段覆盖（分子式/分子量/CAS/UNII/功能分类/FDA IIG 最大用量；ClinicalTrials 应为空）。
- 4.2 单元：阿司匹林（原料药）字段覆盖（分子式/CAS/作用机制/Top 不良反应/FDA 适应症/黑框警告/ClinicalTrials；FDA IIG 应为空）。
- 4.3 单元：莫洛替尼（靶向药）——商品名识别、靶点、开发商检测正确。
- 4.4 单元：circliq（商品名）→ 识别通用名 Acalabrutinib。
- 4.5 错误隔离单测：工具内部抛异常 → 返回友好提示，不向上抛出。
- 4.6 错误隔离单测：mock 数据源为 `sleep` → 60s 返回"查询超时"。
- **产出**：pytest 用例 + 覆盖率报告。

### 阶段 5：全链路自审（Self-Audit）
- 5.1 代码自审：确认未修改其他 30 工具的代码与全局状态（API Key / 配置 / DB）。
- 5.2 耦合自审：确认速查工具不调用其他工具对象、不依赖全局变量，完全解耦。
- 5.3 策略自审：逐条核对六大策略（扩展 / 解析 / CAS / 并行 / 降级 / 置信度 / 路由）均已保留，无简化。
- 5.4 错误隔离自审：运行 `python -c "import tools"` 确认即使 `excipient_basic_info` 导入失败，其他 30 工具仍注册成功。
- 5.5 置信度自审：抽查返回 `Citations` 的 source 与置信度分布是否合理。
- **产出**：《全链路自审清单》（逐条打勾）。

### 阶段 6：端到端测试（E2E）
- 6.1 后端 SSE 接口实测：以"乳糖基本信息""阿司匹林基本信息"走 `/api/chat`，确认速查工具被调用且答案含结构化字段。
- 6.2 错误隔离 E2E：临时让速查工具抛错/超时，确认其他工具与整体应答不受影响。
- 6.3 路由 E2E：辅料查询结果含 FDA IIG、无 ClinicalTrials；原料药反之。
- 6.4 降级 E2E：mock 某数据源 API 失败，确认自动降级到 anysearch 兜底且仍有结果。
- 6.5 验收指标核对：字段覆盖率 ≥ 90%、响应 ≤ 30s、置信度分布合理、CAS 幻觉被纠正。
- **产出**：E2E 测试脚本 + 测试报告。

### 阶段 7：启动服务（Launch & Verify）
- 7.1 拉起后端（uvicorn :8001）与前端（5173）。
- 7.2 在 UI 实测"原辅料基本信息速查"类问题，确认渲染（含已修的 Markdown 表格）。
- 7.3 稳定性验证：速查工具高频调用下 Python 进程不崩溃（路线 B 无 Node 子进程，更稳）。
- 7.4 提交并推送（`git add` / `commit` / `push` 到已建 GitHub 仓库）。
- **产出**：运行服务 + 验收结论 + 提交记录。

---

## 三、沿用原提示词的风险与缓解
- 跨语言风险（路线 A）→ 选路线 B 规避。
- API Key → 当前 `.env` 已配，无需复制。
- 数据源 API 过期 → E2E 阶段逐源检查。
- 置信度不一致 → 聚合层统一映射。
- 字段杜撰 → 严格对照 jiansuo3 字段清单。
- 子模块耦合 → 遵守错误隔离铁律（崩溃/超时/异常/导入失败均不阻断其他工具）。

## 四、一句话总结
**目标可行**：把 jiansuo3 检索内核的六大策略封装为「原辅料基本信息速查」工具；当前版本已具备数据源工具与降级引擎，故推荐纯 Python 聚合方案（路线 B），仅补建「实体解析+CAS 验证」与「置信度分级」，并严守错误隔离铁律。按上述 7 阶段 WBS 推进即可，全程不改动现有 30 工具代码。
