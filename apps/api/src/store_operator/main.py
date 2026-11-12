import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from store_operator.admin_router import router as admin_router
from store_operator.application.system_info import get_system_info
from store_operator.auth.dependencies import SESSION_COOKIE_NAME
from store_operator.auth.errors import ApiError
from store_operator.auth.router import router as auth_router
from store_operator.channel_douyin_router import router as channel_douyin_router
from store_operator.channel_spec_router import router as channel_spec_router
from store_operator.config import settings
from store_operator.content_delivery_router import router as content_delivery_router
from store_operator.content_publishing_router import router as content_publishing_router
from store_operator.content_quality_router import router as content_quality_router
from store_operator.db import engine, redis_client
from store_operator.jobs.router import router as jobs_router
from store_operator.marketing_tasks.router import router as marketing_tasks_router
from store_operator.observability import configure_logging
from store_operator.opportunity_effects_router import router as opportunity_effects_router
from store_operator.prompt_management_router import router as prompt_management_router
from store_operator.store_knowledge_router import router as store_knowledge_router
from store_operator.store_router import router as store_router
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_logging_and_tracing_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
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


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "request_id": request_id,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if isinstance(exc, ApiError):
        error = (exc.code, exc.public_message)
    else:
        error = {
            400: ("BAD_REQUEST", "Bad request"),
            401: ("UNAUTHENTICATED", "Unauthenticated"),
            403: ("FORBIDDEN", "Forbidden"),
            404: ("RESOURCE_NOT_FOUND", "Resource not found"),
            405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
            409: ("CONFLICT", "Conflict"),
            429: ("RATE_LIMITED", "Rate limited"),
            503: ("SERVICE_UNAVAILABLE", "Service unavailable"),
        }.get(exc.status_code, ("HTTP_ERROR", "Request failed"))
    response = _error_response(
        request, status_code=exc.status_code, code=error[0], message=error[1]
    )
    if getattr(request.state, "clear_session_cookie", False):
        response.delete_cookie(
            SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
        )
    return response


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return _error_response(
        request,
        status_code=503,
        code="AUTHORIZATION_UNAVAILABLE",
        message="Authorization service unavailable",
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务暂时不可用",
    )


app.include_router(auth_router, prefix="/api/v1")
app.include_router(store_router, prefix="/api/v1")
app.include_router(store_knowledge_router, prefix="/api/v1")
app.include_router(marketing_tasks_router, prefix="/api/v1")
app.include_router(content_delivery_router, prefix="/api/v1")
app.include_router(channel_douyin_router, prefix="/api/v1")
app.include_router(channel_spec_router, prefix="/api/v1")
app.include_router(content_quality_router, prefix="/api/v1")
app.include_router(content_publishing_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(prompt_management_router, prefix="/api/v1")
app.include_router(opportunity_effects_router, prefix="/api/v1")


@app.get("/health/live", tags=["health"])
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
def ready() -> JSONResponse:
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
def system_info() -> dict[str, str]:
    info = get_system_info(app_name=settings.app_name, environment=settings.environment)
    return {
        "name": info.name,
        "environment": info.environment,
        "api_version": info.api_version,
    }

