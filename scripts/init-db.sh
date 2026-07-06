#!/usr/bin/env bash
# =============================================================================
# Paismart RAG - Database Initialization
# =============================================================================
# Wait for MySQL, create database if not exists, run Alembic migrations.
#
# Usage:
#   ./scripts/init-db.sh
#
# Environment variables (read from .env or environment):
#   MYSQL_HOST        (default: localhost)
#   MYSQL_PORT        (default: 3306)
#   MYSQL_ROOT_USER   (default: root)
#   MYSQL_ROOT_PASSWORD (required)
#   MYSQL_DATABASE    (default: paismart)
#   MYSQL_USER        (default: paismart)
#   MYSQL_PASSWORD    (required)
#
# Idempotent: safe to run multiple times.
# =============================================================================

set -euo pipefail

# --- Load .env if present ---
if [ -f .env ]; then
  set -a
  # shellcheck source=/dev/null
  . .env
  set +a
fi

# --- Configuration with defaults ---
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_ROOT_USER="${MYSQL_ROOT_USER:-root}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
MYSQL_DATABASE="${MYSQL_DATABASE:-paismart}"
MYSQL_USER="${MYSQL_USER:-paismart}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:?MYSQL_PASSWORD is required}"

MAX_RETRIES=30
RETRY_INTERVAL=2

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_error() { echo "[ERROR] $*" >&2; }

# --- Wait for MySQL to be ready ---
wait_for_mysql() {
  log_info "Waiting for MySQL at ${MYSQL_HOST}:${MYSQL_PORT} ..."

  local retries=0
  until mysqladmin ping -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" \
    -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASSWORD}" --silent 2>/dev/null; do
    retries=$((retries + 1))
    if [ "${retries}" -ge "${MAX_RETRIES}" ]; then
      log_error "MySQL not reachable after ${MAX_RETRIES} attempts."
      exit 1
    fi
    sleep "${RETRY_INTERVAL}"
  done

  log_ok "MySQL is reachable."
}

# --- Create database if not exists ---
ensure_database() {
  log_info "Ensuring database '${MYSQL_DATABASE}' exists ..."

  local exists
  exists=$(mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" \
    -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASSWORD}" \
    -N -e "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='${MYSQL_DATABASE}';" 2>/dev/null)

  if [ -z "${exists}" ]; then
    mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" \
      -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASSWORD}" \
      -e "CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    log_ok "Database '${MYSQL_DATABASE}' created."
  else
    log_ok "Database '${MYSQL_DATABASE}' already exists."
  fi

  # Ensure application user has access
  mysql -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" \
    -u"${MYSQL_ROOT_USER}" -p"${MYSQL_ROOT_PASSWORD}" \
    -e "GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%'; FLUSH PRIVILEGES;"
  log_ok "Privileges granted for user '${MYSQL_USER}'."
}

# --- Run Alembic migrations ---
run_migrations() {
  if command -v alembic &>/dev/null; then
    log_info "Running Alembic migrations ..."
    alembic upgrade head
    log_ok "Alembic migrations completed."
  else
    log_info "Alembic not found; skipping migrations."
  fi
}

# --- Main ---
log_info "=== Database Initialization ==="

wait_for_mysql
ensure_database
run_migrations

log_ok "Database initialization completed."
exit 0
