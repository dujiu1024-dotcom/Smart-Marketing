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
