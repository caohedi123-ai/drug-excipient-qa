import sys, io, asyncio, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import httpx

URL = "http://localhost:8001/api/chat"

QUERIES = [
    ("comparison 意图", "acalabrutinib 和 ibrutinib 在机制和安全性上有什么区别"),
    ("窄问题意图", "polysorbate 80 在注射剂中的最大用量是多少"),
]

def extract_sections(answer):
    return re.findall(r"^##\s+(.+)$", answer, re.MULTILINE)

async def run_one(label, q):
    async with httpx.AsyncClient(timeout=180.0) as client:
        answer = ""
        async with client.stream("POST", URL, json={"query": q, "thread_id": "e2e-" + label}) as resp:
            print(f"\n=== {label} | HTTP {resp.status_code} ===")
            if resp.status_code != 200:
                print("NON-200!", await resp.aread())
                return
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    if obj.get("type") == "answer":
                        answer += obj.get("content", "")
        print(f"[答案长度] {len(answer)}")
        print(f"[含 '## 总结'] { '## 总结' in answer }")
        print(f"[含 '📚 参考资料'] { '📚 参考资料' in answer }")
        secs = extract_sections(answer)
        print(f"[章节结构] {secs}")
        print("--- 答案开头 400 字 ---")
        print(answer[:400])
        print("--- 答案尾部 700 字 ---")
        print(answer[-700:])
        print("[含 '总结' 二字]", "总结" in answer)

async def main():
    for label, q in QUERIES:
        await run_one(label, q)

asyncio.run(main())
print("\nE2E 完成")
