# 修复任务：FDA IIG 和 FDA UNII 数据源工具 API 地址错误

## 问题现象
用户提问"精致芝麻油作为辅料的作用和优势"时，系统只返回了 DailyMed 的一个洗发水标签页，回答"未找到系统性描述"。但实际 FDA 数据库中芝麻油相关记录超过 56000 条。

## 根因分析
`backend/tools/sources/fda_iig.py` 和 `backend/tools/sources/fda_unii.py` 的 API 地址是**错误的**：

```python
# 当前错误地址（返回 403 Forbidden）
FDA_IIG_URL = "https://precision.fda.gov/api/v1/search"
FDA_UNII_URL = "https://precision.fda.gov/api/v1/search"
```

**验证命令**（WSL 环境）：
```bash
# 错误地址 → 403
curl -s "https://precision.fda.gov/api/v1/search?q=sesame+oil" -w "%{http_code}"

# 正确地址 → 200 + 56633 条结果
curl -s "https://api.fda.gov/drug/label.json?search=inactive_ingredient:sesame+oil&limit=1" | python3 -c "import sys,json; print(json.load(sys.stdin)['meta']['results']['total'])"
```

## 修复方案

### 1. fda_iig.py 修复

**文件路径**：`backend/tools/sources/fda_iig.py`

**修改点**：
1. 将 `FDA_IIG_URL` 改为 `https://api.fda.gov/drug/label.json`
2. 修改 `_search_fda_iig()` 函数的搜索逻辑：
   - 使用 `inactive_ingredient` 字段搜索辅料
   - 返回结果包含：辅料名、给药途径、最大用量、UNII 编号
   - 构造正确的引用链接

**参考实现**：
```python
FDA_IIG_URL = "https://api.fda.gov/drug/label.json"

async def _search_fda_iig(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # 使用 inactive_ingredient 字段搜索
            resp = await client.get(
                FDA_IIG_URL,
                params={
                    "search": f"inactive_ingredient:{query}",
                    "limit": 10
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                
                for i, item in enumerate(results[:10], 1):
                    # 提取辅料信息
                    inactive_ingredients = item.get("inactive_ingredient", [])
                    brand_name = item.get("openfda", {}).get("brand_name", ["N/A"])[0]
                    manufacturer = item.get("openfda", {}).get("manufacturer_name", ["N/A"])[0]
                    route = item.get("openfda", {}).get("route", ["N/A"])[0]
                    set_id = item.get("set_id", "")
                    
                    # 过滤出包含目标辅料的记录
                    matching_ingredients = [
                        ing for ing in inactive_ingredients 
                        if query.lower() in ing.lower()
                    ]
                    
                    if matching_ingredients:
                        content_parts.append(
                            f"[{i}] {brand_name}\n"
                            f"    生产商: {manufacturer}\n"
                            f"    给药途径: {route}\n"
                            f"    含辅料的制剂: {matching_ingredients[0][:200]}"
                        )
                        
                        if set_id:
                            url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
                            citations.append(Citation(
                                id=len(citations) + 1,
                                source_name="FDA IIG",
                                source_url=url,
                                snippet=f"{brand_name} 含 {query}",
                                retrieval_query=query,
                                retrieval_timestamp=Citation.make_timestamp(),
                            ))

        if citations:
            return SearchResult(
                source_name="FDA IIG",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception as e:
        pass

    # 降级到 Tavily 域名搜索
    return tavily_domain_search(
        query + " inactive ingredient FDA",
        domains=["accessdata.fda.gov", "dailymed.nlm.nih.gov"],
        max_results=6,
    )
```

### 2. fda_unii.py 修复

**文件路径**：`backend/tools/sources/fda_unii.py`

**修改点**：
1. 将 `FDA_UNII_URL` 改为 `https://api.fda.gov/drug/label.json`
2. 修改 `_search_fda_unii()` 函数：
   - 使用 `openfda.unii` 字段搜索 UNII 编号
   - 返回结果包含：物质名称、UNII 编号、物质类型、分子式

**参考实现**：
```python
FDA_UNII_URL = "https://api.fda.gov/drug/label.json"

async def _search_fda_unii(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # 使用 substance_name 或 unii 字段搜索
            resp = await client.get(
                FDA_UNII_URL,
                params={
                    "search": f'openfda.substance_name:"{query}"',
                    "limit": 5
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                
                for i, item in enumerate(results[:5], 1):
                    openfda = item.get("openfda", {})
                    substance_name = openfda.get("substance_name", ["N/A"])[0]
                    unii_list = openfda.get("unii", [])
                    unii = unii_list[0] if unii_list else "N/A"
                    brand_name = openfda.get("brand_name", ["N/A"])[0]
                    generic_name = openfda.get("generic_name", ["N/A"])[0]
                    set_id = item.get("set_id", "")
                    
                    content_parts.append(
                        f"[{i}] {substance_name}\n"
                        f"    UNII: {unii}\n"
                        f"    品牌名: {brand_name}\n"
                        f"    通用名: {generic_name}"
                    )
                    
                    if unii and unii != "N/A":
                        url = f"https://precision.fda.gov/uniisearch/srs/unii/{unii}"
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="FDA UNII",
                            source_url=url,
                            snippet=f"{substance_name}, UNII={unii}",
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))

        if citations:
            return SearchResult(
                source_name="FDA UNII",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception as e:
        pass

    return SearchResult.empty("FDA UNII", "API无返回")
```

## 验证方法

修复完成后，运行以下测试：

```bash
# 1. 启动后端服务
cd /mnt/d/药物原辅料知识问答助手/backend
source .venv/bin/activate
python main.py

# 2. 测试芝麻油查询（应该返回大量结果）
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "精致芝麻油作为辅料的作用和优势是什么", "session_id": "test"}'

# 3. 检查日志，确认 fda_iig_tool 和 fda_unii_tool 返回了有效结果
```

**预期结果**：
- FDA IIG 应该返回多个含芝麻油的制剂信息
- FDA UNII 应该返回芝麻油的 UNII 编号
- 最终回答应该包含具体的辅料作用、用量、配伍信息，而不是"未找到"

## 注意事项

1. **不要修改其他工具**，只改 `fda_iig.py` 和 `fda_unii.py`
2. **保持 Tavily 降级逻辑**，API 失败时仍能兜底
3. **保持 Citation 格式不变**，前端依赖 `__citations__:` 标记解析引用
4. **测试多个辅料**：芝麻油、微晶纤维素、硬脂酸镁等，确保通用性

## 相关文件
- `backend/tools/sources/fda_iig.py`（79行）
- `backend/tools/sources/fda_unii.py`（74行）
- `backend/tools/engines/tavily_engine.py`（Tavily 降级逻辑参考）
- `backend/agent/state.py`（Citation 和 SearchResult 数据结构）
