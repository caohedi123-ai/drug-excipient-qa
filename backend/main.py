"""FastAPI 应用入口 - SSE 流式 Chat 服务"""

import json
import re
import uuid
import traceback
from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from config import get_settings
from db.database import get_db, AsyncSessionLocal, init_redis, close_redis, sync_engine
from agent.graph import get_agent_graph
from tools.sanitize import sanitize_query

settings = get_settings()


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
async def chat(http_request: Request, req: ChatRequest):
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
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT id, title, thread_id, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 50"
    ))
    rows = result.fetchall()
    return [
        {"id": r[0], "title": r[1], "thread_id": r[2], "created_at": str(r[3]), "updated_at": str(r[4])}
        for r in rows
    ]


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str, db: AsyncSession = Depends(get_db)):
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
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(text("DELETE FROM conversations WHERE id=:id"), {"id": conversation_id})
    await db.commit()
    return {"status": "ok"}


# === 反馈 ===
@app.post("/api/feedback")
async def submit_feedback(req: FeedbackCreate, db: AsyncSession = Depends(get_db)):
    await db.execute(text(
        "INSERT INTO feedback (message_id, rating, category, comment) VALUES (:mid, :rating, :cat, :comment)"
    ), {"mid": req.message_id, "rating": req.rating, "cat": req.category, "comment": req.comment})
    await db.commit()
    return {"status": "ok"}


# === 健康检查 ===
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
