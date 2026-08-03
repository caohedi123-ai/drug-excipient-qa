# AnySearch 全盘通查与修复报告

## 一、摸排范围与方法

按用户要求对项目全局 anysearch / tavily 使用进行全盘通查，摸排全部调用点与耦合关系：

| 摸排对象 | 结论 |
|---|---|
| `tools/engines/anysearch_engine.py` | ❌ 发现 3 处缺陷（本次修复核心） |
| `tools/engines/tavily_engine.py` + 9 个 source 调用点 | ✅ 协议规范，无需修改 |
| `tools/sources/*`（23 个含检索的 source） | ✅ 已统一走新引擎公开 API，无旧 `/v1/search` 端点残留 |
| `agent/` 层（graph / retrieve / final_search / decide / adjust / plan / state） | ✅ 仅依赖 `anysearch_vertical` / `anysearch_batch` 公开 API，无内部函数耦合 |
| 旧协议痕迹（`/v1/search`、`x-api-key`、旧端点域名） | ✅ 全库无残留（`x-api-key` 仅存在于 Exa 引擎自身，属正常） |

**耦合关系确认**：`anysearch_engine.py` 内部函数（`_parse_*`、`_rpc_call` 等）全库无外部引用；对外只有 `anysearch_vertical` / `anysearch_batch` 两个公开入口被 source 与 agent 层使用，修改引擎不会破坏调用方。

## 二、发现并修复的缺陷（均在 `anysearch_engine.py`）

### 缺陷 1：batch 响应分段索引错位（P0，导致多条结果错位/为空）
- **现象**：3 条 batch 中第 2 条（ip.global 垂直专利）返回空，但单独/单条 batch 调用成功。
- **根因**：`re.split(r"^## Query...", text)` 带捕获组时返回 `[pre, q1, body1, q2, body2, ...]`，body 应在奇数位 `idx*2+1`，原代码用 `bodies[idx+1]` 导致第 2 条取到 query 文本、第 3 条错位。
- **影响面**：所有 batch 调用——`excipient_basic_info.py` 专利双检索、`sider.py`、`final_search.py`、`anysearch_fallback.py`。
- **修复**：索引改为 `idx*2+1`，并对无 `## Query` 分段的单条响应做整段解析兜底。

### 缺陷 2：专利条目格式无法解析（P0，导致专利结果缺 URL/摘要）
- **现象**：ip.global / GlobalPatent 返回的专利条目是单行紧凑格式 `- Title: ... URL: <patsnap链接> Assignee: ...`（部分带 `Abstract:` 内嵌摘要），与普通条目的 `- **URL**:` 不同，且带 `=== Bibliographic Data ===` / `--- Legal Status ===` 巨型结构化噪音。
- **根因**：原解析只识别 `- **URL**:`，专利条目 URL 全部丢失，结构化噪音被吞进摘要。
- **修复**：
  - 新增 `_RE_PATENT_TITLE_LINE` / `_RE_INLINE_URL` / `_RE_PATENT_META`，从 Title 行提取 URL、申请人、发明人、公开号、公开日、Abstract 摘要正文；
  - 新增 `_extract_patent_text`，从 `=== Bibliographic Data ===` 段提取 `text:` 专利摘要正文与 `pn:` 公开号、`name:` 申请人/发明人；
  - 新增 `_clean_meta_name` 清理 YAML 噪音（`- address: ... name: APOTEX INC.` → `APOTEX INC.`）；
  - 遇结构化数据段自动跳过，不污染摘要。

### 缺陷 3：ip.global 别名空关键词检索（P1，影响 espacenet/cnipa）
- **现象**：`sub_domain="patent"` 别名映射到 `ip.global` 时 `keyword=""`，GlobalPatent 空关键词检索质量差。
- **修复**：新增 `_fill_patent_keyword`，`ip.global` 且 `keyword` 为空时自动用 query 填充，接入 `anysearch_vertical` / `anysearch_batch` 两条路径。

## 三、验证结果

| 验证项 | 结果 |
|---|---|
| 本地解析单测（多段 batch / 专利段 / 单条 batch / 普通 health 条目） | ✅ 4 场景全过 |
| 真实 3 条 batch（health + ip.global 专利 + health） | ✅ 第 2 条专利段由"空"变为 3 条完整结果（URL/公开号/申请人齐全） |
| espacenet 别名路径（`sub_domain="patent"`）真实调用 | ✅ 3 条结果，keyword 自动填充生效 |
| 全量模块导入（38 个：引擎/source/agent/main） | ✅ 全部成功，无改塌 |
| 速查接口端到端（登录 → `/api/excipient/lookup` 阿可替尼） | ✅ 9 条引用、6 模块齐全（专利信息 3 条），content 含专利摘要 |
| Lint（anysearch_engine.py） | ✅ 0 错误 |
| 后端服务 | ✅ 已重启，`/api/health` ok |

## 四、未改动项（确认健康）

- **tavily 链路**：`tavily_engine.py` + 9 个 source（wikipedia/pubchem/fda_*/drugbank/dailymed/excipient_basic_info/ema）调用规范，未触碰。
- **agent 层**：graph/retrieve/final_search 等的 batch 拆解（`i*2`/`i*2+1`）与引擎分段修复后对齐，无需改动。
- **其他 source**：无 anysearch/tavily 依赖的模块未触碰。
- 临时探测脚本 31 个已全部清理。
