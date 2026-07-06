#!/usr/bin/env bash
# =============================================================================
# Paismart RAG - Elasticsearch Index Initialization
# =============================================================================
# Create the knowledge_base index in Elasticsearch with the IK Chinese
# analyzer (ik_max_word) for full-text search over document content.
#
# Usage:
#   ./scripts/init-es.sh
#
# Environment variables (read from .env or environment):
#   ES_HOST           (default: localhost)
#   ES_PORT           (default: 9200)
#   ES_SCHEME         (default: http)
#
# Idempotent: skips if index already exists.
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
ES_HOST="${ES_HOST:-localhost}"
ES_PORT="${ES_PORT:-9200}"
ES_SCHEME="${ES_SCHEME:-http}"
ES_INDEX="${ES_INDEX:-knowledge_base}"

ES_URL="${ES_SCHEME}://${ES_HOST}:${ES_PORT}"

MAX_RETRIES=30
RETRY_INTERVAL=3

log_info()  { echo "[INFO]  $*"; }
log_ok()    { echo "[OK]    $*"; }
log_error() { echo "[ERROR] $*" >&2; }

# --- Wait for ES to be ready ---
wait_for_es() {
  log_info "Waiting for Elasticsearch at ${ES_URL} ..."

  local retries=0
  until curl -sf "${ES_URL}/_cluster/health" &>/dev/null; do
    retries=$((retries + 1))
    if [ "${retries}" -ge "${MAX_RETRIES}" ]; then
      log_error "Elasticsearch not reachable after ${MAX_RETRIES} attempts."
      exit 1
    fi
    sleep "${RETRY_INTERVAL}"
  done

  log_ok "Elasticsearch cluster is healthy."
}

# --- Create index with mapping ---
create_index() {
  log_info "Ensuring index '${ES_INDEX}' ..."

  # Check if index already exists
  local exists
  exists=$(curl -sf -o /dev/null -w "%{http_code}" "${ES_URL}/${ES_INDEX}" 2>/dev/null)

  if [ "${exists}" = "200" ]; then
    log_ok "Index '${ES_INDEX}' already exists."
    return 0
  fi

  log_info "Creating index '${ES_INDEX}' with IK analyzer mapping ..."

  local response
  response=$(curl -sf -X PUT "${ES_URL}/${ES_INDEX}" \
    -H "Content-Type: application/json" \
    -d "$(cat <<PAYLOAD
{
  "settings": {
    "index": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "analysis": {
        "analyzer": {
          "ik_smart_analyzer": {
            "type": "custom",
            "tokenizer": "ik_smart"
          },
          "ik_max_word_analyzer": {
            "type": "custom",
            "tokenizer": "ik_max_word"
          }
        },
        "filter": {
          "english_stop": {
            "type": "stop",
            "stopwords": "_english_"
          }
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "id": {
        "type": "keyword"
      },
      "document_id": {
        "type": "keyword"
      },
      "title": {
        "type": "text",
        "analyzer": "ik_max_word_analyzer",
        "fields": {
          "keyword": {
            "type": "keyword"
          }
        }
      },
      "content": {
        "type": "text",
        "analyzer": "ik_max_word_analyzer",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 512
          }
        }
      },
      "summary": {
        "type": "text",
        "analyzer": "ik_smart_analyzer"
      },
      "tags": {
        "type": "keyword"
      },
      "source_type": {
        "type": "keyword"
      },
      "file_type": {
        "type": "keyword"
      },
      "file_path": {
        "type": "keyword",
        "index": false,
        "doc_values": false
      },
      "chunk_index": {
        "type": "integer"
      },
      "total_chunks": {
        "type": "integer"
      },
      "created_at": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis"
      },
      "updated_at": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||epoch_millis"
      },
      "metadata": {
        "type": "object",
        "enabled": false
      }
    }
  }
}
PAYLOAD
  )" 2>/dev/null)

  if echo "${response}" | grep -q '"acknowledged":true'; then
    log_ok "Index '${ES_INDEX}' created successfully."
  else
    log_error "Failed to create index: ${response}"
    exit 1
  fi
}

# --- Main ---
log_info "=== Elasticsearch Index Initialization ==="

wait_for_es
create_index

log_ok "Elasticsearch initialization completed."
exit 0
