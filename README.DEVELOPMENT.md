# 开发环境

## 先决条件

- Docker Engine + Docker Compose
- Node.js 26.x，并通过 npm 安装 pnpm 10.8.1：`npm install --global pnpm@10.8.1`
- Python 3.13.x + uv

## 启动基础设施

```bash
cp .env.example .env
# 修改 .env 中 POSTGRES_PASSWORD，并同步 DATABASE_URL
docker compose -f infra/compose/docker-compose.yml up --build -d
```

地址：Web http://localhost:5173；API http://localhost:8000；OpenAPI http://localhost:8000/api/v1/docs；PostgreSQL localhost:5432；Redis localhost:6379；SeaweedFS S3 localhost:8333。

## 本地运行 Web

```bash
pnpm install --frozen-lockfile
pnpm dev:web
```

## 本地运行 API

```bash
cd apps/api
uv sync --locked --extra dev
uv run --locked uvicorn store_operator.main:app --reload --app-dir src
```

## 本地运行 Worker

```bash
cd apps/worker
uv sync --locked && uv run --locked celery -A store_operator_worker.celery_app:celery_app worker --loglevel=INFO --app-dir src
```

## 测试

```bash
cd apps/api && uv sync --locked --extra dev && uv run --locked pytest
cd ../..
pnpm test
pnpm typecheck
pnpm build
```

本 Issue 只交付工程骨架。Worker healthcheck 是基础设施 smoke task，不是具备 PostgreSQL Job/Outbox 持久化和恢复语义的正式 Job Runtime（Issue #9）。登录、门店授权、业务数据模型、真实 AI Provider 和渠道发布尚未实现。

## 浏览器冒烟测试

E2E 环境独立维护在 `apps/e2e`，依赖由 `apps/e2e/uv.lock` 锁定。先启动 Web（终端一）：

```bash
pnpm install --frozen-lockfile
pnpm dev:web
```

再执行浏览器测试（终端二）：

```bash
cd apps/e2e
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked python ../../apps/web/e2e/smoke.py
```

该测试验证工程应用壳的页面响应、主标题、运行状态和能力边界提示，不代表冻结 Demo 的全部业务页面已完成。

## 可观测性

API 默认向标准输出写 JSON 结构化日志；敏感字段（密码、Token、Cookie、Authorization、API Key、数据库连接串等）会在序列化前递归脱敏。请求日志只记录请求 ID、方法、路径、状态码和耗时，不记录请求头、请求体或查询参数。

如需向 OTLP HTTP Collector 导出 Trace，在 `.env` 中配置：

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
```

不配置该变量时，API 仍创建本地 Trace，但不会向外部 Collector 导出。敏感字段脱敏和 SDK Span 导出管线由 API 单元测试覆盖。
