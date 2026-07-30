# 药物原辅料知识问答助手 — 设计文档 V0.7

> 状态：待讨论 | 日期：2026-07-28

## 一、项目定位

面向药物原辅料领域的智能知识问答助手：用户自然语言提问 → 权威数据源检索 → 多步推理整合 → 准确可溯源答案。

本质是 **Agentic RAG**，但不同于经典 RAG 靠向量检索，本项目重度依赖权威数据源，每个源同时支持**结构化 API 精准查询**和**域名定向网页搜索**两种模式。

核心交互形态：纯对话框式界面，无报表/导出/审核等复杂页面。

---

## 二、数据源体系（重构）

### 2.1 设计原则

**之前的错误**：将数据源按"API 查询 / MCP / 网页搜索"设了硬边界，导致 API 数据源只能查结构化字段，无法挖掘其网站上的文献和研究内容。

**正确的设计**：每个权威数据源都同时具备两种访问能力——

```
┌─────────────────────────────────────────────┐
│            每个权威数据源                      │
│                                             │
│  Mode A: 结构化查询 (REST API)               │
│    → 精确数据点：分子量、注册号、适应症列表      │
│                                             │
│  Mode B: 域名定向搜索 (Tavily domain filter)  │
│    → 文献/报告/公告/研究内容                   │
│    → 搜 pubchem.ncbi.nlm.nih.gov 上的论文     │
│    → 搜 fda.gov 上的审批文件和安全通告          │
└─────────────────────────────────────────────┘
```

### 2.2 权威数据源列表

按功能域组织。每个源均标注 API 可用性和进入门槛，所有源也同时开放给 Tavily 做域名定向搜索。

#### 药物/化合物基础信息

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `pubchem` | PubChem (NIH) | pubchem.ncbi.nlm.nih.gov | REST ✅ | 免费无认证 | 化学结构、SMILES、分子量、logP、文献 |
| `chembl` | ChEMBL (EBI) | ebi.ac.uk/chembl | REST ✅ / MCP | 免费无认证 | 生物活性(Ki/IC50)、分子靶点、ADMET属性 |
| `drugbank` | DrugBank | go.drugbank.com | REST ⚠️ | 免费但需注册账号 | 靶点、作用机制、药物代谢、ATC分类 |
| `drugcentral` | DrugCentral | drugcentral.org | REST ✅ | 免费无认证 | 药物标签、生物活性、适应症、禁忌症 |
| `coconut` | COCONUT | coconut.naturalproducts.net | REST ✅ | 免费无认证 | 天然产物结构、来源生物、生物活性 |

#### 药物辅料与制剂

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `fda_iig` | FDA IIG | accessdata.fda.gov | REST ✅ | openFDA免费Key | 非活性成分/辅料数据库，每种辅料的最大用量(Maximum Potency) |
| `fda_unii` | FDA UNII | fdasis.nlm.nih.gov | REST ✅ | 免费无认证 | 辅料唯一标识、同义名映射 |
| `fda_ndc` | NDC Directory | accessdata.fda.gov | REST ✅ | openFDA免费Key | 药品产品标识、厂家、剂型、包装 |
| `dailymed` | DailyMed (NLM) | dailymed.nlm.nih.gov | REST ✅ | 免费无认证 | 美国上市药品说明书全文 |

#### 药品注册与审批

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `fda_drugs` | FDA Drugs@FDA | open.fda.gov | REST ✅ | 免费API Key | NDA/BLA/ANDA审批记录、适应症、标签 |
| `fda_orange` | FDA Orange Book | fda.gov/orangedrug | REST ✅ | openFDA免费Key | 参比制剂、治疗等效性评价 |
| `ema` | EMA | ema.europa.eu | REST ✅ | 免费无认证 | 欧洲上市药品评估报告(EPAR) |
| `cde` | CDE | cde.org.cn | 域名搜索 | 无需认证 | 国内药品审评进度、辅料登记信息 |
| `pmda` | PMDA | pmda.go.jp | 域名搜索 | 无需认证 | 日本药品审批 |

#### 药物安全与相互作用

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `fda_faers` | FDA FAERS | open.fda.gov | REST ✅ | 免费API Key | 不良事件报告数据库(百万级) |
| `sider` | SIDER | sideeffects.embl.de | 域名搜索 | 无需认证 | 药品副作用分类频率、适应症-副作用映射 |
| `ddinter` | DDInter 2.0 | ddinter.scbdd.com | 域名搜索 | 无需认证(开放下载) | 药物-药物相互作用、机制、严重程度 |

#### 药理靶点与基因

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `open_targets` | Open Targets | platform.opentargets.org | GraphQL ✅ | 免费无认证 | 靶点-疾病-药物三元关联、遗传证据 |
| `bindingdb` | BindingDB | bindingdb.org | REST ✅ | 免费无认证 | 蛋白质-配体结合亲和力(Ki, IC50, Kd) |
| `pharmgkb` | PharmGKB/ClinPGx | pharmgkb.org | REST ✅ | 免费无认证 | 药物基因组学、药物-基因交互、PGx指南 |
| `ttd` | TTD | ttd.idrblab.cn | 域名搜索 | 免费无认证 | 3500+药物靶点、40000+药物分子 |

#### 分类标准与指南

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `rxnorm` | RxNorm (NLM) | lhncbc.nlm.nih.gov/RxNav | REST ✅ | 免费无认证 | 药品名称标准化、跨词表映射、NDC关联 |
| `who_atc` | WHO ATC/DDD | atcddd.fhi.no | 域名搜索 | 免费无认证 | 解剖-治疗-化学分类、限定日剂量 |
| `ich` | ICH Guidelines | ich.org | 域名搜索 | 免费无认证 | Q/S/E/M系列指导原则全文 |

#### 文献、专利与综合

| ID | 名称 | 域 | API | 门槛 | 覆盖 |
|----|------|----|-----|------|------|
| `pubmed` | PubMed (NIH) | pubmed.ncbi.nlm.nih.gov | REST ✅ (Entrez) | 免费无认证 | 3400万+生物医学文献摘要 |
| `espacenet` | Espacenet | worldwide.espacenet.com | REST ✅ | 免费无认证 | 全球专利(1.5亿+) |
| `cnipa` | 中国专利局 | cnipa.gov.cn | 域名搜索 | 无需认证 | 中国专利申请与授权 |
| `wikipedia` | Wikipedia | en.wikipedia.org, zh.wikipedia.org | REST ✅ | 免费无认证 | 药物背景知识、历史、社会影响 |
| `clinicaltrials` | ClinicalTrials.gov | clinicaltrials.gov | REST ✅ | 免费无认证 | 全球临床试验注册、结果、状态 |

### 2.3 搜索工具选型 — 三引擎分工

本项目的检索需求不是"选一个搜索引擎"，而是**按检索目的匹配引擎能力**。三个引擎各司其职：

| 引擎 | 核心能力 | 在本项目中的职责 | 额度 |
|------|----------|-----------------|------|
| **Tavily** | 域名定向 + AI 答案生成 + 时间过滤 | **精搜**：在 FDA/EMA/PubChem 等权威域名内精准捞取文献、公告、报告 | 付费额度，保护使用 |
| **AnySearch MCP** | 通用 Web 搜索 + 22 垂直领域 + 批量并行 + 页面正文抽取 | **泛搜 + 兜底**：不限域名宽泛搜索、health/academic 垂直领域搜索、多 query 并行批量搜索、页面全文抓取 | 免费 1000 次/天 |
| **Exa** | 语义神经搜索 + 深度研究 + 相似内容发现 + 结构化输出 | **深研**：按语义（非关键词）理解研究意图，做深层次关联发现、相似论文/专利推荐、结构化数据抽取（outputSchema） | 付费额度，关键问题使用 |

---

### 2.3.1 Tavily — 精搜引擎（用完即止，保护额度）

**核心参数矩阵**（不用浅层搜索，每刀都用刀刃上）：

```python
# 基础精搜：在权威源域名内定向搜索，深度模式
tavily.search(
    query="aspirin COX inhibition mechanism prostaglandin pathway",
    search_depth="advanced",      # 不用basic，advanced返回每结果多片段
    include_domains=["pubchem.ncbi.nlm.nih.gov"],
    include_answer="advanced",     # LLM 生成答案摘要，作为快速校验
    include_raw_content=False,     # 保护额度，非必要不拉原文
    max_results=10,
    time_range="",                 # 默认不限时间。时效性查询时传入"3m"/"1y"
    topic="general"                # 通用搜索。新闻类可切"news"
)
```

**深度用法清单**：

| 能力 | 参数 | 场景 |
|------|------|------|
| 深度搜索 | `search_depth="advanced"` | 复杂药物机制问题，需要多段落交叉验证 |
| AI 答案摘要 | `include_answer="advanced"` | 快速判断该源是否命中，节省 evaluate 判断时间 |
| 时间过滤 | `time_range="6m"` / `"1y"` | "最近有哪些阿司匹林新适应症获批？" |
| 精确匹配 | `include_domains=[...]` | 锁定权威域名，不做无用泛搜 |
| 原始内容 | `include_raw_content=True` | 仅在 evaluate 判定需要原文深入分析时使用 |

---

### 2.3.2 AnySearch MCP — 泛搜引擎（不限域名 + 垂直领域 + 批量并行）

**本项目的 AnySearch 不是备用，是第二引擎**。它有三个 Tavily 不具备的杀手能力：

#### A. 垂直领域搜索（22 个领域，三个直接命中本项目）

```python
# health 领域：药/疾病/临床试验
anysearch.search(
    query="aspirin gastrointestinal bleeding risk factors elderly",
    domain="health",
    freshness="past_year",         # 时效过滤
    content_types=["article", "news", "government"]
)

# academic 领域：sub_domain paper/doi/citation
anysearch.search(
    query="aspirin COX-2 selectivity COX-1 inhibition ratio",
    domain="academic",
    sub_domain="paper",
    freshness="any",
    content_types=["article", "journal"]
)

# ip 领域：sub_domain patent/trademark → 药物专利
anysearch.search(
    query="aspirin extended release formulation patent",
    domain="ip",
    sub_domain="patent"
)
```

#### B. 批量并行搜索（1 次调用跑 5 个 query）

```python
# 不同角度同时搜，不串行等待
anysearch.batch_search(queries=[
    "aspirin mechanism of action COX inhibition prostaglandin",
    "aspirin side effects gastrointestinal bleeding risk",
    "aspirin drug interactions warfarin ibuprofen",
    "aspirin cardiovascular prevention clinical guidelines 2024",
    "aspirin excipient compatibility microcrystalline cellulose"
], max_results=8)  # results per query
```

#### C. 页面正文提取（找到的 URL 深度抓取）

```python
# evaluate 判定某篇文献高度相关 → 抓全文
anysearch.extract(
    url="https://example.com/aspirin-review-2024.html",
    max_chars=50000,
    include_tables=True
)  # 返回 Markdown，保留表格结构
```

---

### 2.3.3 Exa — 深研引擎（语义神经搜索 + 关联发现）

Exa 的核心差异在于**按语义匹配而非关键词匹配**。在本项目中，Exa 解决的是"我大概知道想问什么，但关键词不够精确"的场景。

**核心参数矩阵**：

```python
# 场景一：深度语义研究（不限域名，从全网找相关学术内容）
exa.search(
    query="structure-activity relationship of non-steroidal anti-inflammatory COX inhibitors",
    type="deep-reasoning",         # 多步推理搜索，自动分解+再搜索
    category="research publication",  # 限定学术出版物
    include_domains=[],            # 不限域名，语义发现
    autoPromptDate=False,
    numResults=15
)

# 场景二：发现相似文献/专利
exa.findSimilar(
    url="https://pubmed.ncbi.nlm.nih.gov/33451779/",
    excludeSourceDomain="",
    numResults=10
)  # 基于已知论文找引用链、相似研究方向

# 场景三：结构化数据抽取
exa.search(
    query="aspirin PK parameters Cmax Tmax half-life bioavailability",
    outputSchema={
        "drug": "string",
        "cmax": "string",
        "tmax": "string",
        "half_life": "string",
        "bioavailability": "string",
        "source": "string"
    }  # 直接输出结构化 JSON，不返回网页链接
)
```

**深度用法清单**：

| 能力 | 参数 | 场景 |
|------|------|------|
| 深度推理搜索 | `type="deep-reasoning"` | 复杂多跳问题："阿司匹林→COX抑制→前列腺素→血小板聚集这条通路的文献" |
| 相似发现 | `findSimilar(url=...)` | 已知一篇关键论文，找其引用链和类似研究 |
| 结构化抽取 | `outputSchema={...}` | 需要精确数值对比（PK参数、不良反应发生率等） |
| 学术出版物限定 | `category="research publication"` | 排除博客/新闻噪音，只要学术来源 |
| 语义高亮 | `highlights=True` | 只提取段落中的相关高亮部分，节省 token |
| 域名定向 | `include_domains=[...]` | 需要指定权威源时可用，但语义能力远强于 Tavily |

---

### 2.4 三引擎在工具层中的编排

每个数据源工具内部根据检索目的自动匹配引擎：

```
source_tool("pubchem", query="aspirin mechanism of action")
    │
    ├── API (REST): 结构化属性数据 → {molecular_weight, SMILES, logP...}
    │       命中则返回，不消耗任何搜索额度
    │
    ├── Tavily (精搜): include_domains=["pubchem.ncbi.nlm.nih.gov"]
    │       domain 内搜文献/研究报告/记录页面
    │       场景：API 返回的数据需要文献佐证时
    │
    └── Exa (深研 可选): type="deep", category="research publication"
            语义搜索 + 结构化抽取
            场景：问题要求较深层次机理分析时由 evaluate 触发

evaluate 节点判定信息不足时：
    ├── AnySearch.batch_search(多个改写 query 并行跑)
    ├── AnySearch.search(health垂直领域)
    └── Exa.findSimilar(基于已有命中发现类似内容)
```

**核心原则**：API 优先（免费不耗额度）→ Tavily 域名精搜（精准验证）→ 不够则 Exa 深研（语义扩展）→ 仍不够 AnySearch 泛搜（全面兜底）。不是线性 fallback 链，`evaluate` 节点根据信息缺口动态编排组合。

---

### 2.5 LangGraph 自身的 Web 搜索能力

> **结论：LangGraph 没有内置 Web 搜索能力。**

LangGraph 是一个纯编排框架（stateful graph runtime），不包含任何搜索引擎。它的定位是：

- 定义 Agent 状态图（节点 + 边 + 条件路由）
- 管理 checkpoint 持久化与状态恢复
- 提供 streaming / human-in-the-loop 基础设施

所有搜索能力必须通过以下方式**外部注入**：

1. **自定义 Tool 函数**：`@tool` 装饰器包装的 Python 函数，内部调 Tavily SDK / AnySearch MCP / Exa SDK
2. **MCP Server**：通过 `langchain-mcp-adapters` 将外部 MCP 服务的工具注册进 LangGraph 图
3. **LangChain 集成**：如 `langchain_community.tools.TavilySearchResults` 预包装工具

**本项目中的做法**：24 个数据源工具全部用 Tool 函数包装 → 注册到 LangGraph 的 `ToolNode` → LLM 通过 function calling 选择调用。三搜索引擎（Tavily/AnySearch/Exa）作为这些工具函数内部的底层引擎，不直接暴露给 LLM。

---

### 2.6 强制引用追溯体系

> **硬性要求：每个回答中的每条事实性陈述必须附带可追溯的来源链接。不满足此要求的回答不得返回给用户。**

#### 2.6.1 引用数据模型

```python
class Citation(TypedDict):
    id: int                          # 引用序号 [1], [2], ...
    source_name: str                 # 数据源名，如 "PubChem" / "FDA FAERS" / "PubMed"
    source_url: str                  # 可点击直达的 URL
    snippet: str                     # 被引用段落的原文摘录（≤200字）
    retrieval_query: str             # 检索时使用的 query，用于调试和验证
    retrieval_timestamp: str         # ISO 8601 检索时间戳
```

#### 2.6.2 引用生成链路

```
工具调用 → 返回 SearchResult（含 url + snippet）
    │
    ▼
State.citations.append(Citation)   # 每个工具返回时自动追加
    │
    ▼
synthesize 节点：
  1. 从 State.citations 取出所有引用
  2. 生成回答正文时，在每处事实陈述后用 [N] 标注对应的引用序号
  3. 回答末尾附 "参考资料" 节，列出所有引用及其可点击链接
    │
    ▼
前端 Chat UI：
  1. 回答正文中的 [N] 渲染为可点击角标
  2. hover 显示 snippet 预览
  3. 点击跳转 source_url
  4. "参考资料" 节列出完整引用列表
```

#### 2.6.3 各搜索引擎对引用的数据结构保证

| 引擎 | 单条结果的 URL 字段 | snipper 字段 | 其他可用元数据 |
|------|--------------------|-------------|--------------|
| Tavily | `result.url` | `result.content` | `result.title`, `result.score` |
| AnySearch | `result.url` | `result.snippet` / `result.description` | `result.title`, `result.domain` |
| Exa | `result.url` | `result.text` / `result.highlights` | `result.title`, `result.publishedDate`, `result.author` |
| REST API (PubChem/FDA等) | 构造规范 URL | API 返回的描述字段 | 数据版本/更新时间 |

所有引擎返回的结构均有 `url` 字段，可以直接映射到 `Citation.source_url`。对于 REST API（如 PubChem 返回的分子量），系统应构造标准 URL（如 `https://pubchem.ncbi.nlm.nih.gov/compound/<CID>`）作为追溯链接。

#### 2.6.4 synthesize 节点的硬约束

```python
# synthesize 节点的 system prompt 强制指令
SYNTHESIZE_SYSTEM_PROMPT = """
你是药物原辅料知识问答助手。回答时遵守以下铁律：

1. 每一个事实性陈述必须用 [N] 标注引用序号（N 来自 citations 列表）
2. 无法找到来源的信息 → 明确告知用户"该信息在已检索的权威源中未找到"
3. 绝不编造引用链接，绝不伪造 source_url
4. 回答末尾必须包含"参考资料"章节，列出所有引用的完整信息（序号、来源名、可点击 URL）
5. 对于数值型事实（分子量、剂量、LD50 等），每个数值必须单独标注其来源引用

示例输出格式：
---
阿司匹林的分子量为 180.16 g/mol [1]，其通过不可逆抑制 COX-1 和 COX-2 发挥抗炎作用 [2]。

参考资料：
[1] PubChem - Aspirin Compound Summary
    https://pubchem.ncbi.nlm.nih.gov/compound/2244
[2] FDA - Aspirin Label (DailyMed)
    https://dailymed.nlm.nih.gov/dailymed/...
---
"""
```

#### 2.6.5 前端展示规范

| 元素 | 渲染方式 |
|------|---------|
| 文中 `[N]` 角标 | 蓝色可点击 superscript 样式，hover 弹 tooltip 显示 snippet |
| 参考资料列表 | 回答底部独立区域，序号 + 超链接 + 检索时间，灰色底区分正文 |
| URL 有效性 | 不做前端校验。若后端记录中 `source_url` 为空则标记为灰色不可点 |

---

## 三、技术选型

### 3.1 总览

| 层 | 选型 | 理由 |
|----|------|------|
| Agent 框架 | **LangGraph (Python)** | 状态图精确控制多步推理流转 |
| LLM | **DeepSeek V4 Pro** | 中英双语优秀，function calling 成熟，成本可控 |
| 后端 | **FastAPI** | Python 同语言，async SSE 流式 |
| 前端 | **React 19 + Vite + shadcn/ui** | 纯对话框 Chat UI |
| 数据库 | **PostgreSQL 16** | 对话/消息/反馈存储 |
| 缓存 | **Redis** | API 响应缓存、会话状态 |
| 精搜 | **Tavily API** | 域名定向深度搜索，额度金贵仅做精搜 |
| 泛搜 | **AnySearch MCP** | 不限域名 + 垂直领域(health/academic/ip) + batch_search 并行 + extract 正文抓取 |
| 深研 | **Exa API** | 语义神经搜索 + deep-reasoning 多步推理 + findSimilar 关联发现 + outputSchema 结构化抽取 |
| ChEMBL | **MCP Server (Docker sidecar)** | 化合物生物活性数据库 |

### 3.2 技术栈全景

```
React 19 + Vite + shadcn/ui                        前端 (纯对话框)
        │ SSE 流式
FastAPI + LangGraph Agent                            后端
        │
┌───────┼──────────┬───────────┬──────────┬───────────┐
│       │          │           │          │           │
PostgreSQL   Redis   Tavily API  AnySearch  Exa API   ChEMBL
                      (精搜)     MCP(泛搜)  (深研)   MCP
```

---

## 四、核心架构

### 4.1 Agent 状态图

```
START → understand → plan → retrieve → evaluate
                  ↑                         │
                  └─── 信息不足 (≤3轮) ←─────┘
                                              │ 充分
                                         synthesize → RESPONSE
```

| 节点 | 职责 |
|------|------|
| **understand** | 实体识别、意图分类、子问题拆分、关键词构造 |
| **plan** | 选择对应的权威数据源 + 构造查询词（中英双语变体） |
| **retrieve** | 并行调用数据源工具（API + domain search 双模式），自动追加 Citation 到 State |
| **evaluate** | 判断信息是否充分回答用户问题 |
| **synthesize** | 多源整合、冲突消解、**强制内联引用 [N]**、写回答 + 参考资料列表 |

```python
# AgentState 类型定义
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]    # 对话历史
    user_query: str                             # 原始用户问题
    sub_questions: list[str]                   # understand 拆分的子问题
    retrieval_results: list[SearchResult]      # 本轮检索返回的原始结果
    citations: list[Citation]                  # 累积引用列表（跨轮次追加）
    round_count: int                           # 当前检索轮次（≤3）
    is_sufficient: bool                        # evaluate 判定是否足够
    final_answer: str                          # synthesize 生成的最终回答
```

**关键约束**：`retrieve` 节点的每个工具返回结果时，必须从中提取 `url` + `snippet` → 构造 `Citation` 对象 → `State.citations.append()`。`synthesize` 节点只能使用 `State.citations` 中已有引用，不得自行编造。

### 4.2 工具设计（核心）

每个数据源封装为一个工具，内置 API + 搜索引擎双模式。共约 24 个工具，LLM 通过 function calling 直接选择。

**统一返回格式**：每个工具返回时除了检索内容，必须附带结构化的引用元数据：

```python
@dataclass
class SearchResult:
    """单个检索结果的统一容器"""
    source_name: str          # 数据源名
    content: str              # 检索内容（API 返回 + 搜索摘要，合并后 ≤ 3000 字符）
    citations: list[Citation] # 该结果中可追溯的引用列表（必填）
    raw_urls: list[str]       # 额外发现的 URL（默认空）


# ===== 搜索引擎包装函数 =====
def tavily_domain_search(query: str, domains: list[str], 
                         depth="advanced", answer=True, time_range=None):
    """Tavily 域名定向精搜，仅用于有明确权威域名的源"""

def anysearch_vertical(query: str, domain="health", 
                       sub_domain=None, freshness="any"):
    """AnySearch 垂直领域搜索，不限域名"""

def anysearch_batch(queries: list[str], max_results=8):
    """AnySearch 批量并行搜索，多个 query 同时跑"""

def exa_deep_search(query: str, category="research publication",
                    include_domains=None, outputSchema=None):
    """Exa 语义深研，可选结构化抽取"""


# ===== 工具注册（24个，按引擎能力匹配） =====
TOOLS = {
    # === 药物/化合物基础信息（API 主力 + Tavily 域名佐证） ===
    "pubchem":       lambda q: api_pubchem(q) + tavily_domain_search(q, ["pubchem.ncbi.nlm.nih.gov"]),
    "chembl":        lambda q: mcp_chembl(q),                                    # MCP 自足
    "drugbank":      lambda q: api_drugbank(q) + tavily_domain_search(q, ["go.drugbank.com"]),
    "drugcentral":   lambda q: api_drugcentral(q) + anysearch_vertical(q, "health"),
    "coconut":       lambda q: api_coconut(q) + anysearch_vertical(q, "health"),

    # === 辅料与制剂 ===
    "fda_iig":       lambda q: api_fda_iig(q) + tavily_domain_search(q, ["accessdata.fda.gov"]),
    "fda_unii":      lambda q: api_fda_unii(q),                                   # API 自足
    "fda_ndc":       lambda q: api_fda_ndc(q),                                    # API 自足
    "dailymed":      lambda q: api_dailymed(q) + tavily_domain_search(q, ["dailymed.nlm.nih.gov"]),

    # === 注册与审批 ===
    "fda_drugs":     lambda q: api_openfda(q) + tavily_domain_search(q, ["open.fda.gov", "fda.gov"]),
    "fda_orange":    lambda q: api_orange_book(q) + tavily_domain_search(q, ["fda.gov/orangedrug"]),
    "ema":           lambda q: api_ema(q) + tavily_domain_search(q, ["ema.europa.eu"]),
    "cde":           lambda q: anysearch_vertical(q, "health", freshness="past_year"),
    "pmda":          lambda q: anysearch_vertical(q, "health"),

    # === 安全与相互作用 ===
    "fda_faers":     lambda q: api_faers(q),                                       # 专用 API
    "sider":         lambda q: anysearch_vertical(q, "health") 
                              + anysearch_vertical(q, "academic"),                  # 双重领域
    "ddinter":       lambda q: anysearch_vertical(q, "health"),

    # === 靶点与基因 ===
    "open_targets":  lambda q: api_open_targets(q) + anysearch_vertical(q, "academic"),
    "bindingdb":     lambda q: api_bindingdb(q),                                   # API 自足
    "pharmgkb":      lambda q: api_pharmgkb(q) + anysearch_vertical(q, "health"),
    "ttd":           lambda q: anysearch_vertical(q, "health"),

    # === 分类标准与指南（无 API，纯搜索） ===
    "rxnorm":        lambda q: api_rxnorm(q),                                      # API 自足
    "who_atc":       lambda q: anysearch_vertical(q, "health"),
    "ich":           lambda q: anysearch_vertical(q, "health") 
                              + anysearch_vertical(q, "academic"),                  # 指导原则文献

    # === 文献、专利与综合 ===
    "pubmed":        lambda q: api_pubmed(q) + exa_deep_search(
                             q, category="research publication"),                   # Exa 深研语义搜索
    "espacenet":     lambda q: api_espacenet(q) + anysearch_vertical(q, "ip", sub_domain="patent"),
    "cnipa":         lambda q: anysearch_vertical(q, "ip", sub_domain="patent"),
    "wikipedia":     lambda q: api_wikipedia(q),                                   # API 自足
    "clinicaltrials": lambda q: api_ct(q) + anysearch_vertical(q, "health"),
}
```

**每个工具内部的引擎分配逻辑**：
- 有明确 API 的源 → API 优先（免费不耗额度），用 Tavily/AnySearch/Exa 补文献/佐证
- 无 API 的源（cde/pmda/sider/ich 等）→ AnySearch 垂直领域搜索，利用 health/academic/ip 领域分类提高精度
- 文献源（pubmed）→ Exa 语义搜索 + category=research publication 过滤噪音
- 专利源（espacenet/cnipa）→ AnySearch ip 领域 + sub_domain=patent

**工具数量：约 24 个**。不限制 LLM 调用工具的数量——单一数据源命中率不可靠，鼓励 LLM 在 `plan` 节点中尽可能多地选择相关数据源，并对每个源构造差异化 query（中英变体、不同侧重角度）做**多轮并行检索**。信息不充分时由 `evaluate` 驱动扩源+换词回流，详见 4.3。

### 4.3 信息不足的应对策略

当 `evaluate` 节点判定信息不充分时，按优先级依次尝试：

1. **换查询词 + 扩数据源**：中英互译、同义词、CAS号变体调整检索角度 → 上一轮没选的工具全部加入 → 重新并行检索
2. **AnySearch batch_search 批量并行**：将问题拆成 3-5 个不同角度的 query 同时跑（不限域名），利用 health/academic/ip 垂直领域分类提高信号精度
3. **Exa 深研介入**：调用 `exa.search(type="deep-reasoning")` 语义搜索 + `exa.findSimilar()` 基于已有命中发现关联内容，解决"关键词搜不到但语义相关"的问题
4. **AnySearch extract 正文深度抓取**：对已有 URL 中高相关的页面做全文提取（max_chars=50000），避免因摘要信息不足错判
5. **明确告知**：三轮后仍不足，诚实告诉用户哪些信息找到了、哪些没找到，不编造

**引用跨轮累积**：每轮 `retrieve` 追加引用时使用唯一 ID（自增或 UUID），不覆盖前一轮引用。`synthesize` 使用全量 `State.citations`，确保最终回答覆盖所有检索轮次的来源。

### 4.4 数据持久化

```sql
conversations(id, title, thread_id, created_at, updated_at)
messages(id, conversation_id, role, content, citations JSONB, thinking_steps JSONB, created_at)
-- citations JSONB 示例: [{"id":1,"source_name":"PubChem","source_url":"https://...","snippet":"...","retrieval_query":"...","retrieval_timestamp":"..."}]
feedback(id, message_id, rating 1-5, category, comment, created_at)
```

多轮对话：LangGraph `PostgresSaver` checkpoint 自动持久化到 PostgreSQL。

---

## 五、交互设计

纯对话框 Chat 界面。强制引用追溯为系统级硬约束（详见 2.6），前端展示规范：

```
┌──────────────────────────────────────────────┐
│  ☰ 对话列表                    + 新建对话      │ ← 侧栏可折叠
├──────────────────────────────────────────────┤
│                                              │
│  [用户] 阿司匹林的作用机制是什么？              │
│                                              │
│  [AI] 阿司匹林通过不可逆抑制环氧合酶(COX)...    │
│       全文内 [1] [2] [3] 为蓝色可点击角标       │
│       ───────────────────────────────────     │
│       📚 参考资料                              │
│       [1] PubChem - Aspirin Summary           │ ← hover 显示 snippet
│           pubchem.ncbi.nlm.nih.gov/compound/.. │    点击跳转原文
│       [2] DrugBank - Aspirin MOA              │
│           go.drugbank.com/drugs/DB00945       │
│       [3] PubMed - PMID 33451779              │
│           pubmed.ncbi.nlm.nih.gov/33451779/   │
│       ───────────────────────────────────     │
│       ▼ 思考过程 (可折叠)                       │
│       ① 实体识别：阿司匹林=Aspirin/CID 2244    │
│       ② 检索pubchem → 结构/机制信息            │
│       ③ 检索drugbank → MOA靶点验证            │
│       ④ 检索pubmed → 文献佐证                  │
│                                              │
│  [用户] 那它有什么副作用？   ← 多轮对话，自动指代 │
│                                              │
├──────────────────────────────────────────────┤
│  [输入框]                          [发送]     │
└──────────────────────────────────────────────┘
```

关键交互：
- **流式输出**：AI 回复逐字出现，非一次性返回
- **引用卡片**：每个关键事实标注来源，可点击跳转
- **思考过程**：可折叠面板，展示 Agent 推理链（选了哪些源、搜了什么词）
- **多轮对话**：支持指代消解、追问、澄清
- **👍👎 反馈**：每条回复底部可评分

---

## 六、落地路径

### Phase 1：MVP（2周）
- FastAPI + LangGraph 骨架（5节点状态图）
- Tavily API 集成（域名定向精搜，search_depth=advanced + include_answer）
- AnySearch MCP 集成（泛搜 + vertical domain(health/academic/ip) + batch_search + extract）
- 重点数据源工具（约 12 个，覆盖药物基础/辅料/注册/安全/分类/文献）
  pubchem / drugbank / drugcentral / fda_iig / fda_unii / dailymed /
  fda_drugs / fda_faers / cde / rxnorm / pubmed / wikipedia
- 纯对话框 Chat UI + SSE 流式
- PostgreSQL 建表 + LangGraph checkpoint 持久化
- Redis 缓存层

### Phase 2：质量（2周）
- Exa API 集成（语义深研 + findSimilar + outputSchema 结构化抽取）
- 数据源扩展：chembl(MCP) / ema / open_targets / bindingdb / pharmgkb / sider / ddinter
  / fda_orange / who_atc / espacenet / clinicaltrials / cnipa / coconut / ttd / ich
- 信息不足应对策略全链路（换词→batch_search→Exa 深研→extract→诚实告知）
- 冲突消解 + 引用完整性
- 回答质量评估

### Phase 3：深度（按需）
- Exa 使用优化（outputSchema 复杂结构化抽取模板调优）
- 对比分析 + 多跳推理
- 思考过程可视化增强

---

## 七、待讨论关键决策

### ~~Q1 — LLM 方案~~ ✅ DeepSeek V4 Pro
### ~~Q2 — 向量知识库~~ ✅ 第一版不做

### ~~Q3 — 搜索体系~~ ✅ 已确定
三引擎分工：Tavily 精搜（域名定向 + advanced depth + include_answer）+ AnySearch 泛搜（vertical domain + batch_search + extract）+ Exa 深研（deep-reasoning + findSimilar + outputSchema）。引擎按检索目的匹配，evaluate 节点动态编排，不做线性 fallback。

### ~~Q3.5 — LangGraph 搜索能力~~ ✅ 已确认
LangGraph 是纯编排框架，无内置搜索。所有搜索通过 @tool 函数外部注入（Tavily SDK / AnySearch MCP / Exa SDK），ToolNode 注册后 LLM 通过 function calling 选择。

### ~~Q3.6 — 引用追溯~~ ✅ 已确定
硬性要求：每条事实性陈述必须附带可追溯来源链接。Citation 数据结构统一，跨轮累积，synthesize 节点强制内联 [N] 标注 + 参考资料列表。前端渲染可点击角标。

### ~~Q4 — 数据源覆盖~~ ✅ 已确定
当前 24 个权威源按 7 组划分，不再增删。

### ~~Q5 — 前端~~ ✅ 已确定
React 19 + Vite + shadcn/ui 纯对话框方案，认可。

### ~~Q6 — 部署（D 盘约束）~~ ✅ 已确定

**硬性约束：所有持久化存储必须在 D 盘，C 盘只能放配置/日志级别的小文件。**

| 组件 | D 盘部署方案 | 说明 |
|------|------------|------|
| **项目代码** | 已在 `D:\药物原辅料知识问答助手\` | ✅ 天然满足 |
| **Docker Desktop** | 安装到 D 盘；Settings → Resources → Advanced → Disk image location → `D:\docker\data` | Docker 镜像、容器、volume 全部落 D 盘 |
| **WSL2 数据** | `wsl --export` → `D:\wsl\docker-data.tar` → `wsl --import` 到 `D:\wsl\docker-desktop-data` | Docker 后端 WSL2 发行版数据也走 D 盘 |
| **ChEMBL MCP** | Docker sidecar 容器，镜像/数据走上述 D 盘路径 | 自动跟随 Docker 存储位置 |
| **PostgreSQL** | 安装到 `D:\PostgreSQL\`；data 目录设 `D:\pgdata\` | 或 Docker Compose 挂载 volume 到 `D:\pgdata` |
| **Redis** | 安装到 `D:\Redis\`；或 Docker Compose 挂载 volume 到 `D:\redisdata\` | 二选一，Docker 方式更统一 |

**Docker Desktop 关键配置步骤**（安装后执行一次）：
1. Docker Desktop → Settings → Resources → Advanced → **Disk image location** → 改为 `D:\docker\data`
2. 若使用 WSL2 后端：`wsl --shutdown` → `wsl --export docker-desktop-data D:\wsl\backup.tar` → `wsl --unregister docker-desktop-data` → `wsl --import docker-desktop-data D:\wsl\docker-desktop-data D:\wsl\backup.tar`
3. PostgreSQL/Redis 的 Docker Compose volume 挂载点全部写 D 盘绝对路径

**docker-compose.yml 示例（关键挂载路径）**：
```yaml
services:
  postgres:
    image: postgres:16
    volumes:
      - D:/pgdata:/var/lib/postgresql/data    # 数据落 D 盘

  redis:
    image: redis:7-alpine
    volumes:
      - D:/redisdata:/data                     # 数据落 D 盘

  chembl-mcp:
    image: xxx/chembl-mcp:latest               # 镜像存储自动跟随 Docker 配置
    # 无本地持久化需求
```

**结论：完全可以做到 C 盘零占用（除 Docker Desktop 本体安装文件约 500MB 外）。** 实施时按上述配置执行即可。
