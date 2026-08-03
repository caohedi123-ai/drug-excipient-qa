import asyncio, json, sys
from agent.graph import get_agent_graph

async def test():
    graph = await get_agent_graph()
    state = {
        'messages': [],
        'user_query': '阿司匹林的作用机制是什么',
        'sub_questions': [],
        'retrieval_results': [],
        'citations': [],
        'round_count': 0,
        'is_sufficient': False,
        'final_answer': '',
        'thinking_steps': [],
        '_plan': [],
    }
    config = {'configurable': {'thread_id': 'deploy-e2e-001'}}
    print('=== E2E部署验证 ===')
    print(f"Query: {state['user_query']}")
    result = await graph.ainvoke(state, config=config)
    print(f"轮次: {result.get('round_count')}")
    print(f"充分: {result.get('is_sufficient')}")
    print(f"思考: {len(result.get('thinking_steps', []))} 步")
    print(f"引用: {len(result.get('citations', []))} 条")
    print(f"回答: {len(result.get('final_answer', ''))} 字符")
    print(f"回答预览: {result.get('final_answer', '')[:200]}...")
    print('=== 部署验证通过 ===')

if __name__ == '__main__':
    asyncio.run(test())
