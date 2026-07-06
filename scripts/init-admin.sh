#!/usr/bin/env bash
# =============================================================================
# Paismart RAG - Admin User Bootstrap
# =============================================================================
# Bootstrap the initial admin user via the Auth API.
# Reads credentials from .env and POSTs to the backend registration endpoint.
#
# Usage:
#   ./scripts/init-admin.sh
#
# Environment variables (read from .env or environment):
#   BACKEND_URL       (default: http://localhost:8000)
#   ADMIN_EMAIL       (default: admin@paismart.ai)
#   ADMIN_PASSWORD    (default: Admin123!)
#   ADMIN_USERNAME    (default: admin)
#   ADMIN_NICKNAME    (default: Admin)
#
# Idempotent: returns 0 if user already exists (HTTP 409) or is created.
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
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
REGISTER_ENDPOINT="${BACKEND_URL}/api/v1/auth/register"

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@paismart.ai}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123!}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_NICKNAME="${ADMIN_NICKNAME:-Admin}"

MAX_RETRIES=30
RETRY_INTERVAL=3

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_error() { echo "[ERROR] $*" >&2; }

# --- Wait for backend API to be ready ---
wait_for_backend() {
  log_info "Waiting for backend at ${BACKEND_URL} ..."

  local retries=0
  until curl -sf "${BACKEND_URL}/health" &>/dev/null; do
    retries=$((retries + 1))
    if [ "${retries}" -ge "${MAX_RETRIES}" ]; then
      log_error "Backend not reachable after ${MAX_RETRIES} attempts."
      exit 1
    fi
    sleep "${RETRY_INTERVAL}"
  done

  log_ok "Backend is reachable."
}

# --- Register admin user ---
register_admin() {
  log_info "Registering admin user '${ADMIN_USERNAME}' ..."

  local payload
  payload=$(cat <<EOF
{
  "email": "${ADMIN_EMAIL}",
  "password": "${ADMIN_PASSWORD}",
  "username": "${ADMIN_USERNAME}",
  "nickname": "${ADMIN_NICKNAME}"
}
EOF
)

  local http_code
  http_code=$(curl -s -o /tmp/paismart-admin-response.json -w "%{http_code}" \
    -X POST "${REGISTER_ENDPOINT}" \
    -H "Content-Type: application/json" \
    -d "${payload}" 2>/dev/null)

  case "${http_code}" in
    200|201)
      log_ok "Admin user '${ADMIN_USERNAME}' created successfully."
      ;;
    409)
      log_ok "Admin user '${ADMIN_USERNAME}' already exists (skipped)."
      ;;
    422)
      log_error "Validation error:"
      cat /tmp/paismart-admin-response.json >&2
      exit 1
      ;;
    *)
      log_error "Unexpected HTTP ${http_code}:"
      cat /tmp/paismart-admin-response.json >&2
      exit 1
      ;;
  esac
}

# --- Main ---
log_info "=== Admin User Bootstrap ==="

wait_for_backend
register_admin

log_ok "Admin bootstrap completed."
exit 0
