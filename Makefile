COMPOSE_FILE=infra/compose/docker-compose.yml
.PHONY: up down logs web-install web-dev test build typecheck

up:
	docker compose -f $(COMPOSE_FILE) up --build -d

down:
	docker compose -f $(COMPOSE_FILE) down

logs:
	docker compose -f $(COMPOSE_FILE) logs -f --tail=200

web-install:
	pnpm install

web-dev:
	pnpm dev:web

test:
	cd apps/api && uv run --extra dev pytest
	pnpm test

typecheck:
	pnpm typecheck

build:
	pnpm build
