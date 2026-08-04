"""E2E v2: 改造后全链路验证 — 重点测试实体记忆+中断+新图拓扑"""
import asyncio, json, httpx, sys, time

# Windows 重定向 stdout 默认 GBK，无法编码 ® 等字符，强制 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:18082"
results = []

def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(f"  {'[PASS]' if cond else '[FAIL]'} {name}" + (f" — {detail}" if detail else ""))

async def sse_chat(query, conv_id=None, thread_id=None, timeout=300):
    body = {"query": query, "conversation_id": conv_id, "thread_id": thread_id}
    events = []
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as c:
        async with c.stream("POST", f"{BASE}/api/chat", json=body) as resp:
            buffer = ""
            async for chunk in resp.aiter_bytes():
                try: buffer += chunk.decode("utf-8")
                except: continue
                while "\n\n" in buffer:
                    raw, buffer = buffer.split("\n\n", 1)
                    for line in raw.strip().split("\n"):
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data == "[DONE]": events.append({"type": "[DONE]"})
                            else:
                                try: events.append(json.loads(data))
                                except: pass
    return events

def aggregate_answers(events):
    """聚合所有 answer 事件：合并内容、收集 citations（后端仅最后一片携带引用）。"""
    ans_events = [e for e in events if e.get("type") == "answer"]
    content = "".join(e.get("content", "") for e in ans_events)
    citations = [c for e in ans_events for c in (e.get("citations") or [])]
    conv_id = next((e.get("conversation_id") for e in ans_events if e.get("conversation_id")), None)
    thread_id = next((e.get("thread_id") for e in ans_events if e.get("thread_id")), None)
    return {"content": content, "citations": citations,
            "conversation_id": conv_id, "thread_id": thread_id,
            "events": ans_events}

async def main():
    print("="*60)
    print("E2E v2: 改造后全链路验证")
    print("="*60)

    # [1] 基础功能
    print("\n[1] 基础检索: aspirin molecular weight")
    e1 = await sse_chat("aspirin molecular weight")
    agg1 = aggregate_answers(e1)
    ans = agg1["events"][0] if agg1["events"] else None
    check("Answer event", ans is not None)
    check("Has MW", "180" in agg1["content"])
    check("[DONE]", any(e.get("type")=="[DONE]" for e in e1))
    check("Has citations", len(agg1["citations"])>0, f"answer_events={len(agg1['events'])}, citations={len(agg1['citations'])}")

    # [2] 追问：实体记忆测试（阿可替尼 → 追问）
    print("\n[2] 实体记忆: acalabrutinib → follow-up dosage")
    e2a = await sse_chat("what is acalabrutinib", conv_id=None, thread_id=None)
    agg2a = aggregate_answers(e2a)
    ans2a = agg2a["events"][0] if agg2a["events"] else None
    check("acalabrutinib answered", ans2a is not None)
    content2a = agg2a["content"].lower()
    has_acalabrutinib = "acalabrutinib" in content2a or "calquence" in content2a
    check("Content about acalabrutinib", has_acalabrutinib)
    cid1 = agg2a["conversation_id"]
    tid1 = agg2a["thread_id"]
    check("UUID returned", bool(cid1) and bool(tid1))

    # 追问：那它的用法用量？
    print("\n  追问: what about its dosage...")
    e2b = await sse_chat("what about its dosage and administration", conv_id=cid1, thread_id=tid1)
    content2b = aggregate_answers(e2b)["content"].lower()
    
    # 关键验证：追问回答应跟踪正确实体（不串药），有剂量信息或如实说明未找到
    not_aspirin = "aspirin" not in content2b
    mention_acalabrutinib = "acalabrutinib" in content2b or "calquence" in content2b
    # entity memory: 不能串药，必须提及正确实体
    entity_ok = not_aspirin and mention_acalabrutinib
    check("追问: entity memory correct (about acalabrutinib, NOT aspirin)", entity_ok,
          f"not_aspirin={not_aspirin}, mentions_acalabrutinib={mention_acalabrutinib}")
    # dosage: 有剂量信息 或 如实说明剂量未找到（都是正确行为）
    has_dosage_or_honest = any(w in content2b for w in ["dosage","dos","mg","dose","administer","twice","bid","未找到","not found","not available","no dosage"])
    check("追问: dosage info or honest 'not found'", has_dosage_or_honest,
          f"content preview: {content2b[:200]}")

    # [2.5] 中文追问：阿可替尼 → 那它的用法用量呢？（原 bug 场景）
    print("\n[2.5] 中文实体记忆: 阿可替尼 → 那它的用法用量呢")
    e25a = await sse_chat("阿可替尼是什么药", conv_id=None, thread_id=None)
    agg25a = aggregate_answers(e25a)
    ans25a = agg25a["events"][0] if agg25a["events"] else None
    check("阿可替尼 answered", ans25a is not None)
    content25a = agg25a["content"].lower()
    cid25 = agg25a["conversation_id"]
    tid25 = agg25a["thread_id"]
    check("阿可替尼 UUID returned", bool(cid25) and bool(tid25))

    print("  追问: 那它的用法用量呢...")
    e25b = await sse_chat("那它的用法用量呢", conv_id=cid25, thread_id=tid25)
    content25b = aggregate_answers(e25b)["content"].lower()
    # 关键验证：不能窜药，不能识别成阿司匹林
    chinese_entity_fail = "阿司匹林" in content25b or "aspirin" in content25b
    chinese_has_dosage = any(w in content25b for w in ["剂量","用法","用量","mg","每日","口服","给药","administration","dosage","dose"])
    check("中文追问: NOT 阿司匹林", not chinese_entity_fail,
          f"contains_aspirin={chinese_entity_fail}")
    check("中文追问: has dosage info", chinese_has_dosage,
          f"content preview: {content25b[:200]}")

    # [3] 对话隔离：新对话应有独立实体
    print("\n[3] 异实体: ibuprofen molecular weight (new conv)")
    e3 = await sse_chat("ibuprofen molecular weight", conv_id=None, thread_id=None)
    agg3 = aggregate_answers(e3)
    cid3 = agg3["conversation_id"]
    content3 = agg3["content"].lower()
    is_ibuprofen = "ibuprofen" in content3 and "206" in content3
    check("About ibuprofen", is_ibuprofen)
    check("Different UUID", cid3 != cid1, f"c1={cid1}, c3={cid3}")

    # [4] verify: 第一对话的消息仍然正确
    print("\n[4] 对话隔离验证: conv1 messages still correct")
    async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
        r = await c.get(f"{BASE}/api/conversations/{cid1}/messages")
        msgs = r.json()
        arr = msgs if isinstance(msgs, list) else msgs.get("messages",[])
        qs = [m["content"] for m in arr if m.get("role")=="user"]
        check("Conv1 has acalabrutinib Q", any("acalabrutinib" in q.lower() for q in qs))
        check("Conv1 does NOT have ibuprofen Q", all("ibuprofen" not in q.lower() for q in qs))

    async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
        r = await c.get(f"{BASE}/api/conversations/{cid3}/messages")
        msgs3 = r.json()
        arr3 = msgs3 if isinstance(msgs3, list) else msgs3.get("messages",[])
        qs3 = [m["content"] for m in arr3 if m.get("role")=="user"]
        check("Conv3 has ibuprofen Q", any("ibuprofen" in q.lower() for q in qs3))

    # [5] 对话列表
    print("\n[5] 对话列表完整性")
    async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
        r = await c.get(f"{BASE}/api/conversations")
        convs = r.json()
        arr = convs if isinstance(convs, list) else convs.get("conversations",[])
        ids = [x.get("id") for x in arr]
        check("≥2 conversations", len(arr) >= 2, f"count={len(arr)}")
        check("Conv1 in list", cid1 in ids)
        check("Conv3 in list", cid3 in ids)

    # Summary
    print("\n"+"="*60)
    passed = sum(1 for _,ok,_ in results if ok)
    failed = sum(1 for _,ok,_ in results if not ok)
    print(f"RESULTS: {passed} PASS / {failed} FAIL / {len(results)} TOTAL")
    for name, ok, detail in results:
        if not ok: print(f"  FAIL: {name}  |  {detail}")
    print("="*60)
    return failed==0

if __name__=="__main__": asyncio.run(main())
