"""
调试工具调用和 Citation 解析
"""
import asyncio, json

async def test():
    from tools.sources.pubchem import pubchem_tool
    from tools.sources.wikipedia import wikipedia_tool
    from tools import TOOLS_BY_NAME

    for tool_name in ["pubchem_tool", "wikipedia_tool"]:
        tool_fn = TOOLS_BY_NAME.get(tool_name)
        query = "aspirin mechanism of action"
        print(f"\n=== {tool_name} ===")
        try:
            result = tool_fn.invoke(query)
            if asyncio.iscoroutine(result):
                result = await result
            result_str = str(result)
            print(f"Type: {type(result).__name__}")
            has_citation = "__citations__:" in result_str
            print(f"Has __citations__: {has_citation}")
            print(f"First 300 chars: {result_str[:300]}")
            if has_citation:
                parts = result_str.split("__citations__:", 1)
                json_part = parts[1].strip()
                citations = json.loads(json_part)
                print(f"Citations: {len(citations)}")
                for c in citations:
                    print(f"  [{c['id']}] {c['source_name'][:30]}")
        except Exception as e:
            import traceback
            print(f"Error: {type(e).__name__}: {e}")
            traceback.print_exc()

asyncio.run(test())
