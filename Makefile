COMPOSE_FILE=infra/compose/docker-compose.yml
COMPOSE=docker compose --env-file .env -f $(COMPOSE_FILE)
.PHONY: up down logs web-install web-dev test build typecheck seed-prompts

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

web-install:
	pnpm install --frozen-lockfile

web-dev:
	pnpm dev:web

test:
	cd apps/api && uv sync --locked --extra dev
	cd apps/api && uv run --locked pytest
	cd apps/worker && uv sync --locked
	pnpm test

typecheck:
	pnpm typecheck

build:
	pnpm build

seed-prompts:
	$(COMPOSE) exec -T api python -m store_operator.cli seed-prompt-templates $(if $(PUBLISHER_EMAIL),--publisher-email $(PUBLISHER_EMAIL),)
