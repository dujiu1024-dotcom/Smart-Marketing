import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract
from opentelemetry.trace import Status, StatusCode
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from store_operator.config import settings
from store_operator.observability import configure_logging
from store_operator.tracing import configure_tracing

configure_logging()
tracer_provider = configure_tracing(settings.app_name, settings.otel_exporter_otlp_traces_endpoint)
tracer = trace.get_tracer("store_operator.api")
logger = structlog.get_logger("http")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        tracer_provider.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
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
async def request_id_logging_and_tracing_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    started_at = time.perf_counter()
    parent_context = extract(dict(request.headers))
    context_token = attach(parent_context)
    try:
        with tracer.start_as_current_span("http.server.request") as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("request.id", request_id)
            try:
                response = await call_next(request)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                span_context = span.get_span_context()
                logger.error(
                    "http.request.failed",
                    request_id=request_id,
                    trace_id=f"{span_context.trace_id:032x}",
                    method=request.method,
                    path=request.url.path,
                    error_type=type(exc).__name__,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                )
                raise
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_status(Status(StatusCode.ERROR))
            span_context = span.get_span_context()
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http.request.completed",
                request_id=request_id,
                trace_id=f"{span_context.trace_id:032x}",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response
    finally:
        detach(context_token)


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

