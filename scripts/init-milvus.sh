#!/usr/bin/env bash
# =============================================================================
# Paismart RAG - Milvus Collection Initialization
# =============================================================================
# Connect to Milvus and create the document_chunks collection with an IVF_FLAT
# index. Uses pymilvus (Python) for the Milvus gRPC connection.
#
# Usage:
#   ./scripts/init-milvus.sh
#
# Environment variables (read from .env or environment):
#   MILVUS_HOST       (default: localhost)
#   MILVUS_PORT       (default: 19530)
#   MILVUS_ALIAS      (default: default)
#
# Idempotent: safe to run multiple times (skips if collection exists).
#
# Dependencies: python3 with pymilvus (`pip install pymilvus`)
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
MILVUS_HOST="${MILVUS_HOST:-localhost}"
MILVUS_PORT="${MILVUS_PORT:-19530}"
MILVUS_ALIAS="${MILVUS_ALIAS:-default}"

COLLECTION_NAME="${MILVUS_COLLECTION:-document_chunks}"
VECTOR_DIM="${MILVUS_VECTOR_DIM:-1024}"
METRIC_TYPE="${MILVUS_METRIC_TYPE:-IP}"
INDEX_TYPE="${MILVUS_INDEX_TYPE:-IVF_FLAT}"
NLIST="${MILVUS_NLIST:-128}"

MAX_RETRIES=20
RETRY_INTERVAL=3

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_error() { echo "[ERROR] $*" >&2; }

# --- Check dependencies ---
check_deps() {
  if ! python3 -c "import pymilvus" 2>/dev/null; then
    log_error "pymilvus is not installed. Install it with: pip install pymilvus"
    exit 1
  fi
}

# --- Wait for Milvus ---
wait_for_milvus() {
  log_info "Waiting for Milvus at ${MILVUS_HOST}:${MILVUS_PORT} ..."

  local retries=0
  until python3 -c "
from pymilvus import connections
try:
    connections.connect(alias='${MILVUS_ALIAS}', host='${MILVUS_HOST}', port='${MILVUS_PORT}')
    connections.disconnect(alias='${MILVUS_ALIAS}')
    exit(0)
except Exception:
    exit(1)
" 2>/dev/null; do
    retries=$((retries + 1))
    if [ "${retries}" -ge "${MAX_RETRIES}" ]; then
      log_error "Milvus not reachable after ${MAX_RETRIES} attempts."
      exit 1
    fi
    sleep "${RETRY_INTERVAL}"
  done

  log_ok "Milvus is reachable."
}

# --- Create collection and index ---
create_collection() {
  log_info "Ensuring collection '${COLLECTION_NAME}' ..."

  python3 -c "
import sys
from pymilvus import connections, utility, Collection, CollectionSchema, FieldSchema, DataType

# Connect
connections.connect(alias='${MILVUS_ALIAS}', host='${MILVUS_HOST}', port='${MILVUS_PORT}')

# Check if collection already exists
if utility.has_collection('${COLLECTION_NAME}'):
    print('[OK]    Collection \"${COLLECTION_NAME}\" already exists.')
    connections.disconnect(alias='${MILVUS_ALIAS}')
    sys.exit(0)

# Define schema
fields = [
    FieldSchema(name='chunk_id', dtype=DataType.INT64, is_primary=True, auto_id=False),
    FieldSchema(name='doc_id', dtype=DataType.INT64),
    FieldSchema(name='chunk_index', dtype=DataType.INT64),
    FieldSchema(name='content', dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name='embedding', dtype=DataType.FLOAT_VECTOR, dim=${VECTOR_DIM}),
]

schema = CollectionSchema(
    fields=fields,
    description='Document chunks for RAG retrieval',
    enable_dynamic_field=False,
)

# Create collection
collection = Collection(
    name='${COLLECTION_NAME}',
    schema=schema,
    using='${MILVUS_ALIAS}',
)
print('[INFO]  Collection \"${COLLECTION_NAME}\" created.')

# Create IVF_FLAT index on the embedding field
index_params = {
    'metric_type': '${METRIC_TYPE}',
    'index_type': '${INDEX_TYPE}',
    'params': {'nlist': ${NLIST}},
}

collection.create_index(
    field_name='embedding',
    index_params=index_params,
    index_name='idx_embedding',
)
print('[OK]    Index \"idx_embedding\" (${INDEX_TYPE}, metric=${METRIC_TYPE}, nlist=${NLIST}) created.')

# Load collection into memory
collection.load()
print('[OK]    Collection loaded into memory.')

connections.disconnect(alias='${MILVUS_ALIAS}')
sys.exit(0)
"

  local status=$?
  if [ "${status}" -ne 0 ]; then
    log_error "Failed to create collection/index."
    exit 1
  fi
}

# --- Main ---
log_info "=== Milvus Collection Initialization ==="

check_deps
wait_for_milvus
create_collection

log_ok "Milvus initialization completed."
exit 0
