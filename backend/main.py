"""FastAPI 应用入口 - SSE 流式 Chat 服务"""

import json
import re
import uuid
import traceback
import hashlib
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import jwt as pyjwt

from config import get_settings
from db.database import get_db, AsyncSessionLocal, init_redis, close_redis, sync_engine
from agent.graph import get_agent_graph
from tools.sanitize import sanitize_query

# 原辅料速查独立入口（条件导入，导入失败不影响其它接口）
try:
    from tools import excipient_basic_info_tool as _excipient_lookup_tool
except Exception:
    _excipient_lookup_tool = None

settings = get_settings()

# ── JWT 认证配置 ──
JWT_SECRET = "pharma-knowledge-assistant-2024-secret-key"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
FIXED_USERNAME = "admin"
FIXED_PASSWORD_HASH = hashlib.sha256("admin@2024".encode()).hexdigest()

# ── 认证依赖 ──
async def requires_auth(authorization: str = Header(None)):
    """JWT Bearer Token 验证中间件依赖。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="认证格式错误")
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效凭证，请重新登录")
    except Exception:
        raise HTTPException(status_code=401, detail="认证失败")


def _split_answer(text: str, size: int = 60) -> list[str]:
    """将最终答案按句末/换行切分为自然块，再聚合成约 size 字符的片段，用于增量流式输出。"""
    if not text:
        return [""]
    segs = re.split(r"(?<=[。.!?！？\n])", text)
    chunks: list[str] = []
    buf = ""
    for s in segs:
        buf += s
        if len(buf) >= size:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks


# === 请求/响应模型 ===
class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, description="用户问题（1-2000字符）")
    conversation_id: str | None = None
    thread_id: str | None = None


class ConversationCreate(BaseModel):
    title: str = "新对话"


class FeedbackCreate(BaseModel):
    message_id: str
    rating: int
    category: str | None = None
    comment: str | None = None


class ExcipientLookupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200, description="原辅料名称（中文名/英文名/商品名/CAS）")


# === 应用生命周期 ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis 不可用时不应让整个后端崩溃（chat 流程并不依赖 Redis）
    try:
        await init_redis()
    except Exception as e:
        print(f"[WARN] Redis 初始化失败，跳过（不影响问答）: {e}", flush=True)

    # 表结构创建失败也只告警，避免 lifespan 抛异常导致所有接口返回 500
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title VARCHAR(255) NOT NULL DEFAULT '新对话',
                    thread_id VARCHAR(255) NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL CHECK (role IN ('user','assistant','system')),
                    content TEXT NOT NULL DEFAULT '',
                    citations JSONB DEFAULT '[]'::jsonb,
                    thinking_steps JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    category VARCHAR(100),
                    comment TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_conversations_thread_id ON conversations(thread_id);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at DESC);
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
            """))
            # 速查历史表
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS lookup_history (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(500) NOT NULL,
                    entity JSONB DEFAULT '{}'::jsonb,
                    modules JSONB DEFAULT '{}'::jsonb,
                    citations JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_lookup_history_created ON lookup_history(created_at DESC);
            """))
            conn.commit()
    except Exception as e:
        print(f"[WARN] 数据库初始化（建表）失败，已跳过: {e}", flush=True)

    yield
    try:
        await close_redis()
    except Exception:
        pass


app = FastAPI(
    title="中诺药物原辅料知识问答助手",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Chat 端点 (SSE 流式) ===
@app.post("/api/chat")
async def chat(http_request: Request, req: ChatRequest, user: str = Depends(requires_auth)):
    agent = get_agent_graph()
    query = sanitize_query(req.query, max_len=2000)  # 入口仅清洗控制字符/零宽，保留长问实体（截断由各源内部处理）

    async def event_generator():
        conversation_id = req.conversation_id or str(uuid.uuid4())
        thread_id = req.thread_id or str(uuid.uuid4())
        config = {
            "configurable": {"thread_id": thread_id},
            # 调用期传入 recursion_limit，覆盖多轮回溯最坏路径，避免 GraphRecursionError
            "recursion_limit": settings.max_retrieval_rounds * 6 + 12,
        }

        # 1) 保存会话 + 用户消息到数据库
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("""
                    INSERT INTO conversations (id, title, thread_id)
                    VALUES (:id, :title, :thread_id)
                    ON CONFLICT (thread_id) DO UPDATE SET updated_at = now()
                """), {"id": conversation_id, "title": query[:50], "thread_id": thread_id})
                await session.execute(text("""
                    INSERT INTO messages (conversation_id, role, content)
                    VALUES (:cid, 'user', :content)
                """), {"cid": conversation_id, "content": query})
                await session.commit()
        except Exception:
            pass

        initial_state = {
            "messages": [{"role": "user", "content": query}],
            "user_query": query,
            "entities": [],
            "intent": "",
            "sub_questions": [],
            "keywords_en": [],
            "keywords_zh": [],
            "_plan": [],
            "retrieval_results": [],
            "search_history": [],
            "citations": [],
            "round_count": 0,
            "failed_tools": [],
            "is_sufficient": False,
            "content_quality": 0.0,
            "confidence": "",
            "missing_info": [],
            "next_action": "",
            "suggestions": [],
            "failure_reasons": [],
            "evaluation_details": {},
            "force_fallback": False,
            "cannot_answer": False,
            "low_confidence": False,
            "final_answer": "",
            "thinking_steps": [],
            "expanded_queries": [],
            "expanded_names": {},
        }

        final_answer = ""
        final_citations = []
        all_thinking_steps = []

        try:
            # 2) 用 astream 替代 astream_events（更可靠，直接产生状态快照）
            async for state in agent.astream(initial_state, config=config, stream_mode="values"):
                # 客户端断开检测：中断流式
                if await http_request.is_disconnected():
                    yield f"data: {json.dumps({'type': 'error', 'message': '连接已中断'})}\n\n"
                    await asyncio.sleep(0)
                    break

                # 推送思考步骤（按长度比较，避免同一 list 对象被就地修改导致引用比对失效）
                steps = state.get("thinking_steps", [])
                if steps and len(steps) > len(all_thinking_steps):
                    all_thinking_steps = list(steps)  # 副本，避免持有同一个可变引用
                    last_step = steps[-1] if steps else ""
                    thinking_data = {
                        "type": "thinking",
                        "steps": steps,
                        "description": last_step if isinstance(last_step, str) else str(last_step),
                    }
                    yield f"data: {json.dumps(thinking_data)}\n\n"
                    await asyncio.sleep(0)  # 强制刷新 SSE 缓冲区

                # 推送最终答案（分块增量流式，避免一次性返回造成「等待空白」）
                if state.get("final_answer"):
                    # 补齐完整的思考/拆解步骤，确保前端展示完整「问题拆解情况」
                    if state.get("thinking_steps"):
                        thinking_data = {
                            "type": "thinking",
                            "steps": state.get("thinking_steps", []),
                            "description": state["thinking_steps"][-1] if state["thinking_steps"] else "",
                        }
                        yield f"data: {json.dumps(thinking_data, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)
                    final_answer = state["final_answer"]
                    final_citations = state.get("citations", [])
                    pieces = _split_answer(final_answer)
                    for idx, piece in enumerate(pieces):
                        is_last = idx == len(pieces) - 1
                        answer_data = {
                            "type": "answer",
                            "content": piece,
                            "citations": final_citations if is_last else [],
                            "conversation_id": conversation_id,
                            "thread_id": thread_id,
                        }
                        yield f"data: {json.dumps(answer_data, ensure_ascii=False)}\n\n"
                        await asyncio.sleep(0)  # 每个答案分块后立即推送
                    break

            # 3) 循环结束但没收到 final_answer → 异常
            if not final_answer:
                raise RuntimeError("Agent 未生成最终回答，请重试")

        except Exception as e:
            err_msg = str(e)
            tb = traceback.format_exc()
            error_data = {"type": "error", "message": err_msg}
            yield f"data: {json.dumps(error_data)}\n\n"
            await asyncio.sleep(0)
            final_answer = "[处理失败] " + err_msg
            print(f"[ERROR] Chat API: {err_msg}\n{tb}", flush=True)

        finally:
            yield "data: [DONE]\n\n"
            await asyncio.sleep(0)

            # 4) 持久化 AI 回复
            try:
                async with AsyncSessionLocal() as session:
                    await session.execute(text("""
                        INSERT INTO messages (conversation_id, role, content, citations, thinking_steps)
                        VALUES (:cid, 'assistant', :content, CAST(:citations AS jsonb), CAST(:thinking_steps AS jsonb))
                    """), {
                        "cid": conversation_id,
                        "content": final_answer,
                        "citations": json.dumps(final_citations, ensure_ascii=False),
                        "thinking_steps": json.dumps(all_thinking_steps, ensure_ascii=False),
                    })
                    await session.execute(text("""
                        UPDATE conversations SET updated_at = now(), title = :title WHERE id = :id
                    """), {"id": conversation_id, "title": query[:50]})
                    await session.commit()
            except Exception as e:
                print(f"[WARN] Failed to persist AI message: {e}", flush=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# === 对话管理 ===
@app.get("/api/conversations")
async def list_conversations(user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT id, title, thread_id, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 50"
    ))
    rows = result.fetchall()
    return [
        {"id": r[0], "title": r[1], "thread_id": r[2], "created_at": str(r[3]), "updated_at": str(r[4])}
        for r in rows
    ]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    try:
        uuid.UUID(conversation_id)
    except (ValueError, AttributeError):
        return {"messages": []}

    result = await db.execute(text(
        """SELECT id, role, content,
                  COALESCE(citations::text, '[]') AS citations,
                  COALESCE(thinking_steps::text, '[]') AS thinking_steps,
                  created_at
           FROM messages WHERE conversation_id=:cid ORDER BY created_at"""
    ), {"cid": conversation_id})
    rows = result.fetchall()
    msgs = []
    for r in rows:
        try:
            citations = json.loads(r[3])
        except Exception:
            citations = []
        try:
            thinking_steps = json.loads(r[4])
        except Exception:
            thinking_steps = []
        msgs.append({
            "id": r[0], "role": r[1], "content": r[2],
            "citations": citations, "thinking_steps": thinking_steps,
            "created_at": str(r[5])
        })
    return msgs


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(text("DELETE FROM conversations WHERE id=:id"), {"id": conversation_id})
    await db.commit()
    return {"status": "ok"}


# === 反馈 ===
@app.post("/api/feedback")
async def submit_feedback(req: FeedbackCreate, user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(text(
        "INSERT INTO feedback (message_id, rating, category, comment) VALUES (:mid, :rating, :cat, :comment)"
    ), {"mid": req.message_id, "rating": req.rating, "cat": req.category, "comment": req.comment})
    await db.commit()
    return {"status": "ok"}


# === 原辅料速查独立入口（绕过 agent 规划，直接调用速查工具）===
def _parse_lookup_result(raw: str) -> dict:
    """解析速查工具返回值（模块化格式：__MODULES_JSON__ + __CITATIONS__ + __ENTITY__）。"""
    content = raw
    modules = {}
    citations: list = []
    entity = None

    # ── 解析 __MODULES_JSON__ ──
    mm = re.search(r"__MODULES_JSON__\s*:\s*(\{[\s\S]*?\})\s*(?=__|$)", raw, re.DOTALL)
    if mm:
        try:
            modules = json.loads(mm.group(1))
        except Exception:
            modules = {}
        content = raw[:mm.start()].strip()

    # ── 解析 __CITATIONS__ ──
    mc = re.search(r"__CITATIONS__\s*:\s*(\[[\s\S]*?\])\s*(?=__|$)", raw, re.DOTALL)
    if mc:
        try:
            citations = json.loads(mc.group(1))
        except Exception:
            citations = []
        if not mm:  # 如果 __MODULES_JSON__ 没匹配到，从这里截断
            content = raw[:mc.start()].strip()
        content = re.sub(r"\s*__CITATIONS__\s*:.*", "", content, flags=re.DOTALL).strip()

    # ── 解析 __ENTITY__ ──
    me = re.search(r"__ENTITY__\s*:\s*(\{[\s\S]*?\})\s*$", raw, re.DOTALL)
    if me:
        try:
            entity = json.loads(me.group(1))
        except Exception:
            entity = None

    content = re.sub(r"^\[原辅料基本信息速查\]\s*", "", content).strip()
    # 清理残留的 JSON 标记
    content = re.sub(r"__MODULES_JSON__\s*:.*", "", content, flags=re.DOTALL).strip()
    content = re.sub(r"__ENTITY__\s*:.*", "", content, flags=re.DOTALL).strip()

    return {"content": content, "citations": citations, "entity": entity, "modules": modules}


@app.post("/api/excipient/lookup")
async def excipient_lookup(req: ExcipientLookupRequest, user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    """原辅料基本信息速查独立入口：输入名称直接返回速查结果，不走 agent 规划。"""
    if _excipient_lookup_tool is None:
        raise HTTPException(status_code=503, detail="速查工具未加载，请联系管理员")
    try:
        raw = await _excipient_lookup_tool.ainvoke(req.name)
        result = _parse_lookup_result(raw)
        # 自动保存速查历史到数据库
        try:
            history_uuid = uuid.uuid4()
            await db.execute(text("""
                INSERT INTO lookup_history (id, name, entity, modules, citations)
                VALUES (:id, :name, CAST(:entity AS jsonb), CAST(:modules AS jsonb), CAST(:citations AS jsonb))
            """), {
                "id": history_uuid,
                "name": req.name,
                "entity": json.dumps(result.get("entity") or {}, ensure_ascii=False),
                "modules": json.dumps(result.get("modules") or {}, ensure_ascii=False),
                "citations": json.dumps(result.get("citations") or [], ensure_ascii=False),
            })
            await db.commit()
            result["history_id"] = str(history_uuid)
        except Exception:
            await db.rollback()
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "content": f"速查失败：{e}", "citations": [], "entity": None, "modules": {}}


# === 认证 ===
class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

class LoginResponse(BaseModel):
    ok: bool
    token: str = ""
    username: str = ""
    message: str = ""

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """固定账号登录：admin / admin@2024"""
    if req.username != FIXED_USERNAME:
        return {"ok": False, "token": "", "username": "", "message": "用户名错误"}
    pwd_hash = hashlib.sha256(req.password.encode()).hexdigest()
    if pwd_hash != FIXED_PASSWORD_HASH:
        return {"ok": False, "token": "", "username": "", "message": "密码错误"}
    payload = {
        "sub": FIXED_USERNAME,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"ok": True, "token": token, "username": FIXED_USERNAME, "message": "登录成功"}

@app.get("/api/auth/me")
async def me(user: str = Depends(requires_auth)):
    return {"ok": True, "username": user}

# === 速查历史 ===
@app.get("/api/lookup/history")
async def get_lookup_history(user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT id, name, entity, modules, citations, created_at FROM lookup_history ORDER BY created_at DESC LIMIT 50"
    ))
    rows = result.fetchall()
    return [
        {
            "id": str(r[0]), "name": r[1],
            "entity": r[2] if isinstance(r[2], dict) else json.loads(r[2]) if r[2] else None,
            "modules": r[3] if isinstance(r[3], dict) else {},
            "citations": r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]"),
            "created_at": str(r[5]),
        }
        for r in rows
    ]

@app.delete("/api/lookup/history/{history_id}")
async def delete_lookup_history(history_id: str, user: str = Depends(requires_auth), db: AsyncSession = Depends(get_db)):
    await db.execute(text("DELETE FROM lookup_history WHERE id=:id"), {"id": history_id})
    await db.commit()
    return {"status": "ok"}


# === 健康检查 ===
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
