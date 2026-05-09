#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$HOME/backups/feedlite"
STAMP="$(date +%F-%H%M%S)"

cd "$APP_DIR"

echo "==> App dir: $APP_DIR"
echo "==> Backup dir: $BACKUP_DIR"

mkdir -p "$BACKUP_DIR"

DB_BACKUP=""
ENV_BACKUP=""
CONFIG_BACKUP=""

echo "==> Backup local files"

if [ -f "data/feedlite.db" ]; then
  DB_BACKUP="$BACKUP_DIR/db-$STAMP"
  mkdir -p "$DB_BACKUP"
  cp -a data/feedlite.db* "$DB_BACKUP"/
  echo "Backed up data/feedlite.db* -> $DB_BACKUP"
else
  echo "WARN: data/feedlite.db not found, skip db backup"
fi

if [ -f ".env" ]; then
  ENV_BACKUP="$BACKUP_DIR/env.$STAMP"
  cp -a ".env" "$ENV_BACKUP"
  echo "Backed up .env -> $ENV_BACKUP"
fi

if [ -f "config.yml" ]; then
  CONFIG_BACKUP="$BACKUP_DIR/config.yml.$STAMP"
  cp -a "config.yml" "$CONFIG_BACKUP"
  echo "Backed up config.yml -> $CONFIG_BACKUP"
fi

echo "==> Git status before pull"
git status -sb

if git ls-files --error-unmatch config.yml >/dev/null 2>&1; then
  echo "==> config.yml is still tracked locally, restore tracked version before pull"
  git checkout -- config.yml
fi

echo "==> Pull latest code"
git pull --ff-only

echo "==> Ensure local config files still exist"

if [ ! -f ".env" ] && [ -n "$ENV_BACKUP" ]; then
  cp -a "$ENV_BACKUP" ".env"
  echo "Restored .env from backup"
fi

if [ ! -f "config.yml" ] && [ -n "$CONFIG_BACKUP" ]; then
  cp -a "$CONFIG_BACKUP" "config.yml"
  echo "Restored config.yml from backup"
fi

if [ ! -f "config.yml" ] && [ -f "config.example.yml" ]; then
  cp -a "config.example.yml" "config.yml"
  echo "Created config.yml from config.example.yml"
fi

echo "==> Build and restart feedlite"
docker compose up -d --build feedlite

echo "==> Container status"
docker ps --filter "name=feedlite" --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

echo "==> Recent logs"
docker logs --tail=80 feedlite

echo "==> Done"
