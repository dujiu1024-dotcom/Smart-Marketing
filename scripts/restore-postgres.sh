#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/compose/docker-compose.yml"
BACKUP_FILE="${BACKUP_FILE:?Set BACKUP_FILE to an existing custom-format pg_dump file}"
POSTGRES_USER="${POSTGRES_USER:-store_operator}"
POSTGRES_DB="${POSTGRES_DB:-store_operator}"

if [[ ! -f "$BACKUP_FILE" || ! -s "$BACKUP_FILE" ]]; then
  echo "Restore refused: backup file does not exist or is empty: $BACKUP_FILE" >&2
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "Restore is destructive. Set CONFIRM_RESTORE=YES after verifying the target database and backup." >&2
  exit 2
fi

docker compose --project-directory "$ROOT_DIR" -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore --clean --if-exists --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < "$BACKUP_FILE"

printf 'PostgreSQL restore completed from: %s\n' "$BACKUP_FILE"
