# 任务提示词：将 jiansuo3 检索内核迁移到问答助手

## 任务目标

将 `D:\jiansuo3` 项目的**检索内核**（关键词扩展 + 实体解析 + 多数据源并行检索 + 降级策略 + 置信度评估）封装为一个"原辅料基本信息速查"工具，集成到 `D:\药物原辅料知识问答助手\backend\tools\sources\` 中。

**核心原则**：
1. 不是搬 UI，不是搬 API 调用，而是**搬检索策略的实现**。代码可以重构，但策略不能丢。
2. **子模块完全解耦**：无论子模块成功/失败/崩溃/超时，都不影响其他 12 个工具的正常运行。

---

## 背景说明

jiansuo3 项目经过长期调优，形成了一套完整的检索内核，核心能力包括：

1. **LLM 关键词扩展**：将用户输入（中文名/商品名/CAS号）转换为各数据源最可能返回结果的搜索词
2. **实体解析 + CAS 验证**：不信任 LLM 给的 CAS，用 PubChem API 二次验证
3. **多数据源并行检索**：PubChem/Wikipedia/EMA/FAERS/UNII/DrugBank/FDA/DailyMed/PubMed/ClinicalTrials/FDA IIG/Espacenet
4. **3 层降级策略**：API 直连 → AnySearch extract → Tavily/AnySearch 搜索兜底
5. **置信度分级**：API=100, extract=80-90, 搜索=60-70

这套内核保证了检索质量。迁移时必须**完整保留这些策略**，不能简化。

---

## 工具可查询的字段清单（严格依照 jiansuo3 代码）

### PubChem（理化性质，置信度 95-100）
- 分子式
- 分子量
- SMILES
- InChIKey
- XLogP
- 拓扑极性表面积 (TPSA)
- 氢键供体/受体
- 可旋转键
- 重原子
- 精确质量
- ADMET性质（整合字段）
- CAS号（从 synonyms 提取）
- 化学结构（PNG 图片 URL）

### Wikipedia（背景信息，置信度 80）
- 中文名 / 英文名
- CAS号
- 合成方法
- 用途
- 理化性质
- 药品中文名 / 药品英文名
- 分子式
- 作用机制
- 适应症
- 剂型
- 研发/生产（开发商检测：AstraZeneca/Bayer/Pfizer 等）
- 药物类别
- 分子靶点

### EMA EPAR（欧洲监管，置信度 90-95）
- 活性成分
- ATC代码
- EMA适应症
- 欧洲持证商
- 欧洲获批日期
- EMA相关信息（兜底）

### FAERS（不良反应，置信度 90）
- Top不良反应(FAERS)（前 5 名 + 上报数）
- 严重不良反应(FAERS)（serious=1 的前 5 名）

### FDA UNII（辅料标识，置信度 100）
- UNII
- 官方名称

### DrugBank（靶点/机制，置信度 65-90）
- 分子靶点
- 作用机制
- 药物类别
- 应用（辅料功能/用途）
- CAS号
- UNII
- 理化性质（分子式）

### FDA openFDA（药品标签，置信度 90-100）
- 通用名 (Generic Name)
- 商品名 (Brand Name)
- 生产企业
- 给药途径
- 剂型
- FDA适应症
- 用法用量
- 黑框警告
- 警告和注意事项
- 临床药理学
- 药代动力学
- 不良反应
- 功能分类（辅料，关联提取）
- 用量范围（辅料，关联提取）
- 安全性（辅料，关联提取）
- 原研厂家（关联提取）

### PubMed（文献，置信度 60-90）
- 研究论文（标题 + 日期）
- 作者
- 期刊
- DOI
- 临床试验（关联提取）
- Meta分析（关联提取）
- 指南（关联提取）
- 药代动力学（关联提取）
- 安全性研究（辅料，关联提取）
- 辅料应用研究（辅料，关联提取）
- 毒理学（辅料，关联提取）

### DailyMed（说明书，置信度 60-95）
- 药品标签
- DailyMed相关信息（兜底）
- DailyMed摘要（兜底）
- 活性成分（关联提取）
- 适应症（关联提取）
- 用法用量（关联提取）
- 不良反应（关联提取）
- 非活性成分（辅料，关联提取）
- 功能（辅料，关联提取）
- 安全性（辅料，关联提取）

### ClinicalTrials.gov（临床试验，置信度 60-95）
- 临床试验（整合字段：标题、状态、期别、入组、主要终点、疾病、申办）
- NCT编号
- 试验状态
- 研究疾病/条件
- 申办方
- 主要终点
- 次要终点
- 试验阶段（关联提取）
- 适应症（关联提取）
- 入组标准（关联提取）

### FDA IIG（辅料数据库，仅辅料查询，置信度 90-100）
- 辅料名
- 给药途径
- 最大用量
- UNII

### Espacenet（专利，置信度 60-70）
- 专利信息（通过 Tavily/AnySearch 兜底）

---

## 执行步骤

### Phase 1：提取检索内核（从 jiansuo3）

**源文件位置**：`D:\jiansuo3\src\lib\`

需要提取的核心文件：

1. **`llm.ts`**（914 行）
   - `expandKeywords()`：LLM 关键词扩展（第 352-450 行）
   - `resolveEntity()`：PubChem 实体解析（第 207-285 行）
   - `verifyCASNumber()`：CAS 号验证（第 290-347 行）
   - `extractStructuredData()`：从网页内容提取结构化数据
   - `translateFieldValue()` / `translateFieldsBatch()`：英文字段翻译

2. **`data-sources.ts`**（2029 行）
   - `searchPubChem()`：PubChem API（分子量、分子式、SMILES、CAS、ADME）
   - `searchWikipedia()`：Wikipedia REST API → AnySearch extract → Tavily 兜底
   - `searchEMA()`：EMA EPAR 多 URL 模式 extract → AnySearch 兜底
   - `searchFAERS()`：openFDA FAERS 不良反应数据
   - `searchUNII()`：FDA UNII 辅料唯一标识
   - `searchDrugBank()`：AnySearch 搜 → extract 详情 → Tavily 兜底
   - `searchFDAOpenFDA()`：FDA openFDA 药品标签（含关联法）
   - `searchPubMed()`：PubMed 文献（含关联法）
   - `searchDailyMed()`：DailyMed 说明书（含关联法）
   - `searchClinicalTrials()`：ClinicalTrials.gov 临床试验（含关联法）
   - `searchFDAIIG()`：FDA IIG 辅料数据库（仅辅料）
   - `searchEspacenet()`：专利检索（Tavily 兜底）

3. **`anysearch-client.ts`**（AnySearch MCP 封装）
4. **`tavily-client.ts`**（Tavily SDK 封装）
5. **`types.ts`**（类型定义：ModuleName, ReportType, SearchResult 等）
6. **`field-descriptions.ts`**（字段描述映射）
7. **`runtime-config.ts`**（运行时配置：API Key 等）

**提取方式**：
- 将这些文件复制到 `D:\药物原辅料知识问答助手\backend\tools\jiansuo3-core\` 目录
- 保持原有目录结构
- 不要修改核心逻辑，只做必要的路径/导入调整

---

### Phase 2：封装为问答助手工具（含错误隔离）

**目标文件**：`D:\药物原辅料知识问答助手\backend\tools\sources\excipient_basic_info.py`

**工具设计**：

```python
"""原辅料基本信息速查工具 - 封装 jiansuo3 检索内核

功能：输入原辅料名称/CAS号，返回结构化的基本信息，包括：
- 理化性质：分子量、分子式、SMILES、CAS号、InChIKey、XLogP、TPSA、HBD/HBA
- 背景信息：药物类别、作用机制、分子靶点、开发商、用途
- 安全信息：Top 不良反应（FAERS）、黑框警告、警告和注意事项
- 监管信息：FDA 适应症、用法用量、给药途径、剂型、ATC代码、欧洲获批信息
- 辅料专用：UNII、官方名称、最大用量、功能分类（仅辅料查询）
- 文献信息：PubMed 研究论文、DailyMed 说明书、ClinicalTrials 临床试验
- 专利信息：Espacenet/Tavily 专利检索

检索策略（来自 jiansuo3，不可简化）：
1. LLM 关键词扩展：将输入转换为各数据源最优搜索词
2. 实体解析 + CAS 验证：PubChem API 二次验证 CAS 号
3. 多数据源并行：PubChem/Wikipedia/EMA/FAERS/UNII/DrugBank/FDA/DailyMed/PubMed/ClinicalTrials/FDA IIG/Espacenet
4. 3 层降级：API 直连 → AnySearch extract → Tavily/AnySearch 搜索
5. 置信度分级：API=100, extract=80-90, 搜索=60-70
6. 按产品类型路由：辅料查询跳过 ClinicalTrials，启用 FDA IIG；原料药查询跳过 FDA IIG

错误隔离（铁律）：
- 子模块崩溃/超时/异常 → 返回空结果，不影响其他工具
- 不修改全局状态（API Key、配置、数据库连接）
- 不抛出异常到上层（所有异常在内部捕获）
- 可以单独禁用，不影响其他 12 个工具
"""

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
import subprocess
import json
import asyncio


@tool
async def excipient_basic_info_tool(query: str) -> str:
    """原辅料基本信息速查：查询原料药或辅料的理化性质、安全信息、监管信息、文献、专利等。
    适用场景：快速了解某个原辅料的基础信息、理化性质、安全数据、监管状态。
    Input: 原辅料名称/CAS号/商品名（支持中英文）"""
    
    # 错误隔离：所有异常在内部捕获，不抛出
    try:
        result = await _query_excipient_basic_info(query)
        if not result.success:
            return f"[原辅料基本信息速查] 未找到 '{query}' 的相关信息。"
        
        citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
        return f"[原辅料基本信息速查] {result.content}\n\n__citations__: {citations_json}"
    
    except Exception as e:
        # 子模块崩溃 → 返回友好提示，不影响其他工具
        print(f"[BasicInfo] Tool failed (isolated): {e}")
        return f"[原辅料基本信息速查] 查询失败，请稍后重试。（错误已隔离，不影响其他功能）"


async def _query_excipient_basic_info(query: str) -> SearchResult:
    """执行原辅料基本信息速查 - 完整保留 jiansuo3 检索策略"""
    
    # 错误隔离：subprocess 调用 Node.js 脚本
    try:
        result = subprocess.run(
            ["node", "backend/tools/jiansuo3-core/query_basic_info.js", query],
            capture_output=True,
            text=True,
            timeout=60  # 超时 60 秒，防止 Node.js 进程挂起
        )
        
        if result.returncode != 0:
            # Node.js 执行失败 → 返回空结果，不抛异常
            print(f"[BasicInfo] Node.js failed: {result.stderr}")
            return SearchResult.empty("BasicInfo", f"Node.js 执行失败")
        
        # 解析 JSON 输出
        all_records = json.loads(result.stdout)
        
    except subprocess.TimeoutExpired:
        # 超时 → 返回空结果
        print(f"[BasicInfo] Timeout after 60s")
        return SearchResult.empty("BasicInfo", "查询超时")
    
    except json.JSONDecodeError as e:
        # JSON 解析失败 → 返回空结果
        print(f"[BasicInfo] JSON parse failed: {e}")
        return SearchResult.empty("BasicInfo", "结果解析失败")
    
    except FileNotFoundError:
        # Node.js 脚本不存在 → 返回空结果
        print(f"[BasicInfo] Script not found")
        return SearchResult.empty("BasicInfo", "子模块未部署")
    
    except Exception as e:
        # 其他异常 → 返回空结果
        print(f"[BasicInfo] Unexpected error: {e}")
        return SearchResult.empty("BasicInfo", "未知错误")
    
    # 合并结果 + 置信度评估（不可简化）
    citations = []
    content_parts = []
    
    # 按字段分组，去重，选最高置信度
    field_map = {}
    for record in all_records:
        field = record.get("field")
        value = record.get("value")
        confidence = record.get("confidence", 0)
        source = record.get("source", "")
        source_url = record.get("sourceUrl", "")
        
        if not field or not value:
            continue
        
        # 如果字段已存在，选置信度更高的
        if field in field_map:
            if confidence > field_map[field]["confidence"]:
                field_map[field] = {
                    "value": value,
                    "confidence": confidence,
                    "source": source,
                    "sourceUrl": source_url,
                }
        else:
            field_map[field] = {
                "value": value,
                "confidence": confidence,
                "source": source,
                "sourceUrl": source_url,
            }
    
    # 构造输出
    for field, data in field_map.items():
        content_parts.append(f"{field}: {data['value']}")
        
        if data.get("sourceUrl"):
            citations.append(Citation(
                id=len(citations) + 1,
                source_name=data["source"],
                source_url=data["sourceUrl"],
                snippet=f"{field}: {data['value'][:100]}",
                retrieval_query=query,
                retrieval_timestamp=Citation.make_timestamp(),
            ))
    
    if not content_parts:
        return SearchResult.empty("BasicInfo", "未找到相关信息")
    
    return SearchResult(
        source_name="BasicInfo",
        content="\n".join(content_parts)[:8000],
        citations=citations,
        success=True,
    )
```

**关键要求**：
1. **必须调用 jiansuo3 的检索函数**，不要自己重新实现
2. **必须保留 3 层降级策略**（API → extract → 搜索）
3. **必须保留置信度分级**（API=100, extract=80-90, 搜索=60-70）
4. **必须保留 CAS 验证逻辑**（不信任 LLM 给的 CAS）
5. **必须并行检索所有数据源**（不能串行，不能减少数据源）
6. **必须按产品类型路由**（辅料跳过 ClinicalTrials，启用 FDA IIG；原料药反之）
7. **字段列表严格依照上述清单**，不要杜撰不存在的字段
8. **错误隔离（铁律）**：
   - 所有异常在内部捕获，不抛出到上层
   - subprocess 调用必须有 60s 超时
   - 失败时返回空结果，不影响其他工具
   - 不修改全局状态（API Key、配置、数据库连接）

---

### Phase 3：Node.js 入口文件（含错误隔离）

**目标文件**：`D:\药物原辅料知识问答助手\backend\tools\jiansuo3-core\query_basic_info.js`

```javascript
// backend/tools/jiansuo3-core/query_basic_info.js
// Node.js 入口文件 - 封装 jiansuo3 检索内核

import { expandKeywords, resolveEntity, verifyCASNumber } from './llm.js';
import { 
  searchPubChem, searchWikipedia, searchEMA, searchFAERS,
  searchUNII, searchDrugBank, searchFDAOpenFDA, searchPubMed,
  searchDailyMed, searchClinicalTrials, searchFDAIIG, searchEspacenet 
} from './data-sources.js';

const query = process.argv[2];

if (!query) {
  console.error('Usage: node query_basic_info.js <query>');
  process.exit(1);
}

async function main() {
  try {
    // Step 1: LLM 关键词扩展
    const keywords = await expandKeywords(query);
    
    // Step 2: 实体解析 + CAS 验证
    if (keywords.englishName) {
      const entity = await resolveEntity(keywords.englishName);
      if (entity.resolved?.cas && entity.resolved.cas !== keywords.casNumber) {
        const verified = await verifyCASNumber(entity.resolved.cas);
        if (verified.valid) {
          keywords.casNumber = verified.cas;
        }
      }
    }
    
    // Step 3: 判断产品类型
    const isExcipient = keywords.productType === "药用辅料";
    const reportType = isExcipient ? "excipient" : "raw_drug";
    
    // Step 4: 多数据源并行检索
    const tasks = [
      searchPubChem(query, keywords, reportType),
      searchWikipedia(query, keywords, reportType),
      searchEMA(query, keywords, reportType),
      searchFAERS(query, keywords, reportType),
      searchUNII(query, keywords, reportType),
      searchDrugBank(query, keywords, reportType),
      searchFDAOpenFDA(query, keywords, reportType),
      searchPubMed(query, keywords, reportType),
      searchDailyMed(query, keywords, reportType),
      searchEspacenet(query, keywords, reportType),
    ];
    
    if (isExcipient) {
      tasks.push(searchFDAIIG(query, keywords, reportType));
    } else {
      tasks.push(searchClinicalTrials(query, keywords, reportType));
    }
    
    // Step 5: 等待所有任务完成（容错）
    const results = await Promise.allSettled(tasks);
    const allRecords = results
      .filter(r => r.status === 'fulfilled')
      .flatMap(r => r.value);
    
    // Step 6: 输出 JSON
    console.log(JSON.stringify(allRecords));
    
  } catch (error) {
    // 错误隔离：Node.js 崩溃时输出空数组，不抛异常
    console.error('Node.js error:', error.message);
    console.log('[]');  // 返回空数组，Python 端会处理
    process.exit(0);  // 退出码 0，表示"正常退出但无数据"
  }
}

main();
```

**关键要求**：
1. **错误隔离**：所有异常在内部捕获，输出空数组 `[]`，退出码 0
2. **不修改全局状态**：不写文件、不改环境变量、不改数据库
3. **超时控制**：每个数据源函数内部已有 timeout，这里不再额外控制

---

### Phase 4：注册工具到问答助手（可单独禁用）

**文件**：`D:\药物原辅料知识问答助手\backend\tools\__init__.py`

```python
# 药物基础信息组
from tools.sources.pubchem import pubchem_tool
from tools.sources.drugbank import drugbank_tool
from tools.sources.drugcentral import drugcentral_tool

# 辅料与制剂组
from tools.sources.fda_iig import fda_iig_tool
from tools.sources.fda_unii import fda_unii_tool
from tools.sources.dailymed import dailymed_tool

# 注册审批组
from tools.sources.fda_drugs import fda_drugs_tool
from tools.sources.cde import cde_tool

# 安全组
from tools.sources.fda_faers import fda_faers_tool

# 分类文献组
from tools.sources.rxnorm import rxnorm_tool
from tools.sources.pubmed import pubmed_tool
from tools.sources.wikipedia import wikipedia_tool

# 新增：原辅料基本信息速查（子模块，可单独禁用）
try:
    from tools.sources.excipient_basic_info import excipient_basic_info_tool
    BASIC_INFO_TOOL_AVAILABLE = True
except ImportError as e:
    print(f"[Warning] excipient_basic_info_tool not available: {e}")
    BASIC_INFO_TOOL_AVAILABLE = False


# Phase 1 工具列表 (12个 + 1个子模块)
PHASE1_TOOLS = [
    pubchem_tool,
    drugbank_tool,
    drugcentral_tool,
    fda_iig_tool,
    fda_unii_tool,
    dailymed_tool,
    fda_drugs_tool,
    cde_tool,
    fda_faers_tool,
    rxnorm_tool,
    pubmed_tool,
    wikipedia_tool,
]

# 子模块：如果导入失败，不影响其他 12 个工具
if BASIC_INFO_TOOL_AVAILABLE:
    PHASE1_TOOLS.append(excipient_basic_info_tool)


def get_tool_node() -> ToolNode:
    """获取注册了所有工具的 ToolNode"""
    return ToolNode(PHASE1_TOOLS)


def get_tool_descriptions() -> str:
    """生成工具列表描述文本（供LLM的system prompt使用）"""
    lines = ["## 可用数据源工具\n"]
    for t in PHASE1_TOOLS:
        desc = t.description or ""
        lines.append(f"- **{t.name}**: {desc}")
    return "\n".join(lines)
```

**关键要求**：
1. **可单独禁用**：`excipient_basic_info_tool` 导入失败时，其他 12 个工具正常注册
2. **无耦合**：子模块的 ImportError 不影响其他工具的导入
3. **条件注册**：只有导入成功才添加到 `PHASE1_TOOLS`

---

### Phase 5：测试验证

**测试用例**（来自 jiansuo3 的实测数据）：

1. **乳糖（Lactose，辅料）**
   - 预期字段：分子式 C12H22O11, 分子量 342.3, CAS 63-42-3, UNII, 功能分类（填充剂）, 最大用量（FDA IIG）, 非活性成分（DailyMed）
   - 验证：辅料专用字段（FDA IIG、功能分类）有数据，ClinicalTrials 无数据

2. **阿司匹林（Aspirin，原料药）**
   - 预期字段：分子式 C9H8O4, 分子量 180.16, CAS 50-78-2, 作用机制（COX 抑制）, Top 不良反应（FAERS）, FDA 适应症, 用法用量, 黑框警告, 临床试验（ClinicalTrials）
   - 验证：原料药字段（ClinicalTrials、黑框警告）有数据，FDA IIG 无数据

3. **莫洛替尼（Acalabrutinib，靶向药）**
   - 预期字段：分子式 C26H23N7O2, 分子量 456.5, CAS 1420477-60-6, 药物类别（BTK 抑制剂）, 分子靶点（BTK）, 开发商（Acerta/AstraZeneca）, FDA 适应症, 临床试验
   - 验证：商品名识别正确，靶点信息准确，开发商检测正确

4. **circliq（商品名）**
   - 预期：能识别出通用名（Acalabrutinib），返回正确的基础信息
   - 验证：LLM 关键词扩展 + 实体解析工作正常

**错误隔离测试**：

5. **子模块崩溃测试**
   - 操作：删除 `query_basic_info.js` 文件
   - 预期：`excipient_basic_info_tool` 返回"子模块未部署"，其他 12 个工具正常调用

6. **子模块超时测试**
   - 操作：在 `query_basic_info.js` 中加 `await new Promise(r => setTimeout(r, 120000))`（2 分钟）
   - 预期：`excipient_basic_info_tool` 60s 后返回"查询超时"，其他工具不受影响

7. **子模块异常测试**
   - 操作：在 `query_basic_info.js` 中加 `throw new Error('test error')`
   - 预期：`excipient_basic_info_tool` 返回"查询失败"，其他工具正常

**验收标准**：
- ✅ 字段覆盖率 ≥ 90%（与 jiansuo3 对比，严格依照上述字段清单）
- ✅ 置信度分布合理（API=100, extract=80-90, 搜索=60-70）
- ✅ 降级策略生效（API 失败时自动切换到 extract/搜索）
- ✅ CAS 验证生效（LLM 幻觉的 CAS 被纠正）
- ✅ 产品类型路由生效（辅料跳过 ClinicalTrials，原料药跳过 FDA IIG）
- ✅ 响应时间 ≤ 30 秒（与 jiansuo3 持平）
- ✅ **错误隔离生效**：子模块崩溃/超时/异常不影响其他 12 个工具

---

## 错误隔离铁律（不可违反）

1. **子模块崩溃不影响其他模块**
   - Python 工具：所有异常在内部捕获，不抛出到上层
   - Node.js 脚本：所有异常在内部捕获，输出空数组 `[]`，退出码 0
   - subprocess 调用：必须有 60s 超时，超时返回空结果

2. **子模块不修改全局状态**
   - 不修改 API Key、配置文件、环境变量
   - 不修改数据库连接、缓存
   - 不修改其他工具的全局变量

3. **子模块可以单独禁用**
   - 导入失败时，其他 12 个工具正常注册
   - 可以注释掉 `PHASE1_TOOLS.append(excipient_basic_info_tool)`，不影响其他工具
   - 可以删除 `jiansuo3-core/` 目录，不影响其他工具

4. **子模块不依赖其他工具**
   - 不调用 `pubchem_tool`、`drugbank_tool` 等其他工具
   - 不依赖其他工具的全局状态
   - 完全独立运行

5. **子模块的资源独立**
   - Node.js 进程独立于 Python 主进程
   - Node.js 崩溃不会导致 Python 进程崩溃
   - Node.js 内存泄漏不影响 Python 内存

---

## 风险提示

1. **TypeScript → Python 跨语言调用**
   - 风险：subprocess 调用有性能开销，错误处理复杂
   - 缓解：用 Node.js 脚本封装，Python 只负责调用和解析

2. **API Key 配置**
   - 风险：jiansuo3 的 API Key（DeepSeek/Tavily/AnySearch）需要迁移到问答助手
   - 缓解：在问答助手的 `.env` 中配置相同的 Key

3. **数据源 API 变更**
   - 风险：jiansuo3 的 API 调用可能已过期（如 EMA URL 变更）
   - 缓解：测试时检查每个数据源的返回，失败的及时修复

4. **置信度评估不一致**
   - 风险：问答助手的 Citation 模型与 jiansuo3 的 SearchResult 不完全匹配
   - 缓解：在转换层做字段映射，保留 confidence 字段

5. **字段列表不一致**
   - 风险：实现时可能杜撰不存在的字段
   - 缓解：严格依照上述字段清单，不要自行添加

6. **子模块耦合风险**
   - 风险：实现时可能无意中修改全局状态，影响其他工具
   - 缓解：严格遵守"错误隔离铁律"，所有异常在内部捕获

---

## 交付物

1. **`backend/tools/jiansuo3-core/`**：jiansuo3 检索内核代码（TypeScript）
2. **`backend/tools/jiansuo3-core/query_basic_info.js`**：Node.js 入口文件（含错误隔离）
3. **`backend/tools/sources/excipient_basic_info.py`**：Python 工具封装（含错误隔离）
4. **`backend/tools/__init__.py`**：工具注册（已更新，可单独禁用）
5. **测试报告**：4 个功能测试用例 + 3 个错误隔离测试用例

---

## 一句话总结

**把 jiansuo3 的检索内核（关键词扩展 + 实体解析 + 多数据源并行 + 降级策略 + 置信度评估）封装为一个"原辅料基本信息速查"工具，问答助手调用这个工具，而不是自己实现检索逻辑。子模块完全解耦，无论成功/失败/崩溃/超时，都不影响其他 12 个工具的正常运行。**
