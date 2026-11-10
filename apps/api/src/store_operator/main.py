import time
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from store_operator.config import settings
from store_operator.observability import configure_logging

configure_logging()
logger = structlog.get_logger("http")

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)
engine = create_engine(settings.database_url, pool_pre_ping=True)
redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=1)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "http.request.failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http.request.completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unavailable")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务暂时不可用",
                "request_id": request_id,
            }
        },
    )


@app.get("/health/live", tags=["health"])
def live():
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready():
    dependencies: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        dependencies["postgres"] = "ready"
    except SQLAlchemyError:
        dependencies["postgres"] = "unavailable"
    try:
        redis_client.ping()
        dependencies["redis"] = "ready"
    except Exception:
        dependencies["redis"] = "unavailable"

    healthy = all(value == "ready" for value in dependencies.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ready" if healthy else "not_ready",
            "dependencies": dependencies,
        },
    )


@app.get("/api/v1/system/info", tags=["system"])
def system_info():
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "api_version": "v1",
    }
