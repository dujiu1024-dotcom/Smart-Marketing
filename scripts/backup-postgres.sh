#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/compose/docker-compose.yml"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="${BACKUP_FILE:-$BACKUP_DIR/store_operator_$TIMESTAMP.dump}"
POSTGRES_USER="${POSTGRES_USER:-store_operator}"
POSTGRES_DB="${POSTGRES_DB:-store_operator}"

umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

cd "$ROOT_DIR"
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump --format=custom --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  > "$BACKUP_FILE"

if [[ ! -s "$BACKUP_FILE" ]]; then
  rm -f "$BACKUP_FILE"
  echo "Backup failed: output file is empty." >&2
  exit 1
fi

chmod 600 "$BACKUP_FILE"
printf 'PostgreSQL backup created: %s (%s bytes)\n' "$BACKUP_FILE" "$(wc -c < "$BACKUP_FILE" | tr -d ' ')"
