"""E2E 全链路验证：SSE 流式 + 检索质量
测试 1: 直连后端 18082 SSE
测试 2: 通过 Vite 代理 5173 SSE  
测试 3: 阿司匹林用法用量完整链路
"""
import httpx, asyncio, json, time, sys

BASE = "http://127.0.0.1:18082"
PROXY = "http://127.0.0.1:5173"

results = {"pass": 0, "fail": 0, "checks": []}

def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results["checks"].append(f"[{status}] {name} {detail}")
    if ok:
        results["pass"] += 1
    else:
        results["fail"] += 1
    print(f"[{status}] {name} {detail}")

AUTH_HEADERS = {}

def set_auth(token: str):
    global AUTH_HEADERS
    AUTH_HEADERS = {"Authorization": f"Bearer {token}"}

async def login():
    """登录获取 JWT token"""
    async with httpx.AsyncClient(timeout=10, trust_env=False) as c:
        r = await c.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin@2024"})
        data = r.json()
        if data.get("ok"):
            set_auth(data["token"])
            return True, data["token"][:20] + "..."
        return False, data.get("message", "login failed")

async def test_sse_direct():
    """测试 1: 直接连接后端 SSE"""
    print("\n=== Test 1: Direct Backend SSE ===")
    events = []
    start = time.time()
    first_event_time = None
    
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        async with client.stream(
            "POST", f"{BASE}/api/chat",
            json={"query": "aspirin molecular weight", "conversation_id": None, "thread_id": None},
            headers={"Accept": "text/event-stream", **AUTH_HEADERS}
        ) as resp:
            record("SSE direct: status 200", resp.status_code == 200, f"got {resp.status_code}")
            record("SSE direct: Content-Type", 
                   "text/event-stream" in resp.headers.get("content-type", ""),
                   f"content-type={resp.headers.get('content-type')}")
            
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        events.append(("done", data_str))
                        continue
                    try:
                        data = json.loads(data_str)
                        etype = data.get("type", "?")
                        events.append((etype, data))
                        if first_event_time is None:
                            first_event_time = time.time()
                            elapsed = first_event_time - start
                            print(f"  First event: '{etype}' at +{elapsed:.2f}s")
                            record("SSE direct: first event < 10s", elapsed < 10, f"+{elapsed:.1f}s")
                    except json.JSONDecodeError:
                        events.append(("parse_error", data_str[:80]))
    
    total_time = time.time() - start
    thinking_events = [e for e in events if e[0] == "thinking"]
    answer_events = [e for e in events if e[0] == "answer"]
    done_events = [e for e in events if e[0] == "done"]
    
    print(f"  Events: {len(events)} total (thinking={len(thinking_events)}, answer={len(answer_events)}, done={len(done_events)})")
    
    record("SSE direct: has thinking events", len(thinking_events) > 0)
    record("SSE direct: has answer event", len(answer_events) > 0)
    record("SSE direct: has [DONE]", len(done_events) > 0)
    
    if answer_events:
        # 增量流式：答案被拆为多个分块，需拼接后判断完整性；citations 仅末块携带
        content = "".join(e[1].get("content", "") for e in answer_events)
        citations = answer_events[-1][1].get("citations", [])
        record("SSE direct: answer not empty", len(content) > 50, f"{len(content)} chars (joined {len(answer_events)} chunks)")
        record("SSE direct: has citations", len(citations) > 0, f"{len(citations)} citations (last chunk)")
    
    return events


async def test_sse_via_proxy():
    """测试 2: 通过 Vite 代理的 SSE"""
    print("\n=== Test 2: Via Vite Proxy SSE ===")
    events = []          # (etype, data)
    event_times = []     # 记录每个事件到达的绝对时间，用于检测是否流式分散到达（无缓冲）
    start = time.time()
    first_event_time = None
    
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        async with client.stream(
            "POST", f"{PROXY}/api/chat",
            json={"query": "ibuprofen molecular weight and formula", "conversation_id": None, "thread_id": None},
            headers={"Accept": "text/event-stream", **AUTH_HEADERS}
        ) as resp:
            record("SSE proxy: status 200", resp.status_code == 200, f"got {resp.status_code}")
            ct = resp.headers.get("content-type", "")
            print(f"  Proxy Content-Type: {ct}")
            record("SSE proxy: Content-Type", "text/event-stream" in ct, f"ct={ct}")
            
            line_count = 0
            async for line in resp.aiter_lines():
                line_count += 1
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        events.append(("done", data_str))
                        event_times.append(time.time())
                        continue
                    try:
                        data = json.loads(data_str)
                        etype = data.get("type", "?")
                        events.append((etype, data))
                        event_times.append(time.time())
                        if first_event_time is None:
                            first_event_time = time.time()
                            elapsed = first_event_time - start
                            print(f"  First event: '{etype}' at +{elapsed:.2f}s (line #{line_count})")
                            # 首事件（understand 节点 LLM 调用产出）到达时间：受 LLM 首响应延迟影响，15s 为容差
                            record("SSE proxy: first event < 15s", elapsed < 15, f"+{elapsed:.1f}s")
                    except json.JSONDecodeError:
                        events.append(("parse_error", data_str[:80]))
    
    total_time = time.time() - start
    thinking_events = [e for e in events if e[0] == "thinking"]
    answer_events = [e for e in events if e[0] == "answer"]
    done_events = [e for e in events if e[0] == "done"]
    
    print(f"  Events: {len(events)} total (thinking={len(thinking_events)}, answer={len(answer_events)}, done={len(done_events)})")
    print(f"  Total time: {total_time:.1f}s")
    
    record("SSE proxy: has thinking events", len(thinking_events) > 0)
    record("SSE proxy: has answer event", len(answer_events) > 0)
    record("SSE proxy: has [DONE]", len(done_events) > 0)
    
    # 无缓冲检测：事件应流式分散到达（事件间存在明显时间间隔），而非代理缓冲后一次性 dump。
    # 若代理缓冲，所有 data 行会在流结束时几乎同时到达（事件间间隔≈0）。
    if len(event_times) >= 2:
        gaps = [event_times[i+1] - event_times[i] for i in range(len(event_times) - 1)]
        first_gap = gaps[0]
        max_gap = max(gaps)
        streaming = first_gap > 0.05 and max_gap < total_time + 1
        record("SSE proxy: streaming OK (no buffering)", streaming,
               f"first_gap={first_gap:.2f}s max_gap={max_gap:.1f}s events={len(event_times)}")
    else:
        record("SSE proxy: streaming OK (no buffering)", False, "fewer than 2 events")
    
    if answer_events:
        content = "".join(e[1].get("content", "") for e in answer_events)
        citations = answer_events[-1][1].get("citations", [])
        record("SSE proxy: answer not empty", len(content) > 50, f"{len(content)} chars (joined {len(answer_events)} chunks)")
        record("SSE proxy: has citations", len(citations) > 0, f"{len(citations)} citations (last chunk)")
    
    return events


async def test_aspirin_dosage():
    """测试 3: 阿司匹林用法用量 - 检索链路验证"""
    print("\n=== Test 3: 阿司匹林用法用量 ===")
    events = []
    
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        async with client.stream(
            "POST", f"{BASE}/api/chat",
            json={"query": "阿司匹林用法用量 成人剂量 每日最大剂量", "conversation_id": None, "thread_id": None},
            headers={"Accept": "text/event-stream", **AUTH_HEADERS}
        ) as resp:
            record("Aspirin: status 200", resp.status_code == 200)
            
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        events.append(("done", data_str))
                        continue
                    try:
                        data = json.loads(data_str)
                        etype = data.get("type", "?")
                        events.append((etype, data))
                        if etype == "thinking":
                            steps = data.get("steps", [])
                            for s in steps:
                                print(f"  [thinking] {s}")
                    except json.JSONDecodeError:
                        events.append(("parse_error", data_str[:80]))
    
    answer_events = [e for e in events if e[0] == "answer"]
    thinking_events = [e for e in events if e[0] == "thinking"]
    done_events = [e for e in events if e[0] == "done"]
    
    record("Aspirin: has answer", len(answer_events) > 0)
    record("Aspirin: has [DONE]", len(done_events) > 0)
    
    if answer_events:
        content = "".join(e[1].get("content", "") for e in answer_events)
        citations = answer_events[-1][1].get("citations", [])
        conv_id = answer_events[-1][1].get("conversation_id", "")
        
        print(f"  Answer: {len(content)} chars (joined {len(answer_events)} chunks)")
        print(f"  Citations: {len(citations)}")
        print(f"  Preview: {content[:200]}...")
        
        record("Aspirin: answer > 100 chars", len(content) > 100, f"{len(content)} chars (joined)")
        record("Aspirin: has citations", len(citations) > 0, f"{len(citations)}")
        record("Aspirin: has conversation_id", bool(conv_id), f"conv={conv_id[:8]}")
        
        # 检查是否包含中文剂量信息
        has_dose_info = any(word in content for word in ["mg", "剂量", "mg/kg", "每日", "成人", "儿童", "口服"])
        print(f"  Has dose-related content: {has_dose_info}")
        
        if has_dose_info:
            record("Aspirin: contains dosage info", True)
        else:
            record("Aspirin: contains dosage info", False, "no dose keywords found in answer")
    else:
        record("Aspirin: answer > 100 chars", False, "no answer event")

    # 分析 thinking steps 中的检索过程和评估结果
    all_steps = []
    for t in thinking_events:
        all_steps.extend(t[1].get("steps", []))
    
    eval_text = "\n".join(all_steps)
    if "充分" in eval_text:
        record("Aspirin: search quality sufficient", True)
    elif "不足" in eval_text:
        record("Aspirin: search quality sufficient", False, "evaluate says insufficient")
    else:
        record("Aspirin: search quality sufficient", False, "no evaluate result found")
    
    return events


async def main():
    print("=" * 60)
    print("E2E Full Pipeline Verification")
    print("=" * 60)
    
    # Health checks
    async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
        r = await c.get(f"{BASE}/api/health")
        record("Health: backend 18082", r.json()["status"] == "ok")
        r2 = await c.get(f"{PROXY}/api/health")
        record("Health: Vite proxy 5173", r2.json()["status"] == "ok")

    # Login
    ok, detail = await login()
    record("Login: admin", ok, detail)
    
    await test_sse_direct()
    await test_sse_via_proxy()
    await test_aspirin_dosage()
    
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)
    for c in results["checks"]:
        print(f"  {c}")
    print(f"\n  Total: {results['pass']}/{results['pass']+results['fail']} passed")
    
    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
