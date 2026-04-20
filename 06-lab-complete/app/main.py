"""
Production AI Agent — Kết hợp tất cả Day 12 concepts

Checklist:
  ✅ Config từ environment (12-factor)
  ✅ Structured JSON logging
  ✅ API Key authentication
  ✅ Rate limiting
  ✅ Cost guard
  ✅ Input validation (Pydantic)
  ✅ Health check + Readiness probe
  ✅ Graceful shutdown
  ✅ Security headers
  ✅ CORS
  ✅ Error handling
"""
import os
import time
import signal
import logging
import json
from datetime import datetime, timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Security, Depends, Request, Response
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.config import settings

# ─────────────────────────────────────────────────────────
# Agent Core — From Lab 5
# ─────────────────────────────────────────────────────────
from app.core.agent_engine import run_clinical_agent

# ─────────────────────────────────────────────────────────
# Logging — JSON structured
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='{"ts":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

START_TIME = time.time()
_is_ready = False
_request_count = 0
_error_count = 0

# ─────────────────────────────────────────────────────────
# Redis client (Optional fallback to In-memory logic)
r = None
if settings.redis_url:
    try:
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        # Kiểm tra kết nối ngay lập tức
        r.ping()
        logger.info("✅ Connected to Redis")
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed: {e}. Falling back to limited in-memory mode.")
        r = None
else:
    logger.info("ℹ️ No REDIS_URL provided. Running in in-memory mode.")

def check_rate_limit(key: str):
    if not r:
        return # Bỏ qua rate limit nếu không có redis (hoặc có thể dùng in-memory simple logic)
    try:
        now = time.time()
        redis_key = f"rate:{key}"
        # Dùng Sliding Window với Redis Sorted Set
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - 60)
        pipe.zadd(redis_key, {str(now): now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, 60)
        results = pipe.execute()
        
        count = results[2]
        if count > settings.rate_limit_per_minute:
            raise HTTPException(429, f"Rate limit exceeded: {settings.rate_limit_per_minute} req/min")
    except redis.ConnectionError:
        logger.warning("Redis offline - bypassing rate limit")

def check_and_record_cost(user_id: str, input_tokens: int, output_tokens: int):
    if not r:
        return
    try:
        today = time.strftime("%Y-%m-%d")
        redis_key = f"cost:{user_id}:{today}"
        
        current_cost = float(r.get(redis_key) or 0)
        if current_cost >= settings.daily_budget_usd:
            raise HTTPException(503, "Daily budget exhausted")
            
        cost = (input_tokens / 1000) * 0.00015 + (output_tokens / 1000) * 0.0006
        r.incrbyfloat(redis_key, cost)
        r.expire(redis_key, 86400)
    except (redis.ConnectionError, AttributeError):
        pass

# ─────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key or api_key != settings.agent_api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
        )
    return api_key

# ─────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_ready
    logger.info(json.dumps({
        "event": "startup",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }))
    time.sleep(0.1)  # simulate init
    _is_ready = True
    logger.info(json.dumps({"event": "ready"}))

    yield

    _is_ready = False
    logger.info(json.dumps({"event": "shutdown"}))

# ─────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    global _request_count, _error_count
    start = time.time()
    _request_count += 1
    try:
        response: Response = await call_next(request)
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "server" in response.headers:
            del response.headers["server"]
        duration = round((time.time() - start) * 1000, 1)
        logger.info(json.dumps({
            "event": "request",
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": duration,
        }))
        return response
    except Exception as e:
        _error_count += 1
        raise

# ─────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────
class AgentRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)

class AgentResponse(BaseModel):
    question: str
    answer: str
    model: str
    timestamp: str

def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "127.0.0.1"

# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────

@app.get("/", tags=["Info"])
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "endpoints": {
            "ask": "POST /ask (requires X-API-Key)",
            "health": "GET /health",
            "ready": "GET /ready",
        },
    }


@app.post("/ask", response_model=AgentResponse, tags=["Agent"])
async def ask(
    request: AgentRequest,
    client_ip: str = Depends(get_client_ip),
    user_id: str = Depends(verify_api_key)
):
    """EntryPoint chính cho Agent - Đã tích hợp Security & Stateless History."""
    # 1. Rate Limiting (Redis-based)
    check_rate_limit(user_id)
    
    start_time = time.time()
    try:
        # 2. Lấy lịch sử hội thoại từ Redis (Stateless Design)
        formatted_history = []
        history_key = f"history:{user_id}"
        
        if r:
            raw_history = r.lrange(history_key, 0, 9)  # Lấy 10 tin nhắn gần nhất
            chat_history = [json.loads(h) for h in raw_history]
            
            # 3. Map message sang format LangChain (Human/AI)
            for h in chat_history:
                formatted_history.append(("human", h["q"]))
                formatted_history.append(("ai", h["a"]))

        # 4. Gọi Agent thực tế
        answer = run_clinical_agent(request.question, chat_history=formatted_history)
        
        # 5. Lưu lại lịch sử mới vào Redis (nếu có)
        if r:
            new_interaction = json.dumps({"q": request.question, "a": answer}, ensure_ascii=False)
            r.lpush(history_key, new_interaction)
            r.ltrim(history_key, 0, 9)
            r.expire(history_key, 1800)
        
        # 6. Tracking Cost
        q_len = len(request.question)
        a_len = len(answer)
        check_and_record_cost(user_id, q_len, a_len)

        elapsed = (time.time() - start_time) * 1000
        logger.info(f'{{"event": "agent_call", "user": "{user_id}", "ms": {elapsed:.1f}}}')

        return AgentResponse(
            question=request.question,
            answer=answer,
            model=settings.llm_model,
            timestamp=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(f"Agent flow error: {str(e)}")
        raise HTTPException(500, f"Internal Server Error: {str(e)}")


@app.get("/health", tags=["Operations"])
def health():
    """Liveness probe. Platform restarts container if this fails."""
    status = "ok"
    checks = {"llm": "mock" if not settings.openai_api_key else "openai"}
    return {
        "status": status,
        "version": settings.app_version,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Operations"])
def ready():
    """Readiness probe. Load balancer stops routing here if not ready."""
    if not _is_ready:
        raise HTTPException(503, "App not initialized")
    try:
        r.ping()
        return {"ready": True, "redis": "connected"}
    except Exception as e:
        logger.error(f"Readiness check failed: {str(e)}")
        raise HTTPException(503, "Redis connection failed")


@app.get("/metrics", tags=["Operations"])
def metrics(_key: str = Depends(verify_api_key)):
    """Basic metrics (protected)."""
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": _request_count,
        "error_count": _error_count,
        "daily_cost_usd": round(_daily_cost, 4),
        "daily_budget_usd": settings.daily_budget_usd,
        "budget_used_pct": round(_daily_cost / settings.daily_budget_usd * 100, 1),
    }


# ─────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))

signal.signal(signal.SIGTERM, _handle_signal)


if __name__ == "__main__":
    logger.info(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    logger.info(f"API Key: {settings.agent_api_key[:4]}****")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        timeout_graceful_shutdown=30,
    )
