#!/usr/bin/env bash
set -euo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    have "$PYTHON_BIN" || fail "$PYTHON_BIN is not installed"
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi
  if have python3; then
    printf '%s\n' "python3"
    return 0
  fi
  if have python; then
    printf '%s\n' "python"
    return 0
  fi
  fail "python3 or python is not installed"
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_BASE_FILE="${OPENCLAW_ENV_BASE_FILE:-$ROOT_DIR/env.base}"
resolve_env_file_from_args() {
  local prev=""
  for arg in "$@"; do
    if [[ "$prev" == "--env-file" ]]; then
      printf '%s\n' "$arg"
      return 0
    fi
    case "$arg" in
      --env-file=*)
        printf '%s\n' "${arg#*=}"
        return 0
        ;;
    esac
    prev="$arg"
  done
  return 1
}

if resolved_env_file="$(resolve_env_file_from_args "$@" 2>/dev/null)"; then
  ENV_BASE_FILE="$resolved_env_file"
fi

if [[ -f "$ENV_BASE_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_BASE_FILE"
  set +a
fi

PY_DB_SCRIPT="$ROOT_DIR/instance_db.py"
MANUAL_OPS_HELPER="$ROOT_DIR/scripts/manual_operation_state.py"
DB_PATH="${OPENCLAW_DB_PATH:-$ROOT_DIR/openclaw_instances.db}"
DEFAULT_OPENCLAW_VERSION="${OPENCLAW_CURRENT_IMAGE_VERSION:-2026.4.3}"
DEFAULT_OPENCLAW_IMAGE="xen-v${DEFAULT_OPENCLAW_VERSION}"

LOG_DIR="${OPENCLAW_LOG_DIR:-$ROOT_DIR/logs/update}"
LOG_FILE=""

INSTANCE_ID=""
TARGET_VERSION=""
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-}"
OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-}"
manual_log_status="error"

usage() {
  cat <<EOF
Usage:
  $0 --instance-id <id> [options]

Options:
  --version VALUE
  --image-ref VALUE
  --gateway-bind lan|local
  --env-file PATH
  --db-path PATH
  --log-dir PATH
  -h, --help

Notes:
  - Varsayilanlari env.base dosyasindan okur.
  - Reads instance data from SQLite (domain key, ports, volume, tokens).
  - Recreates containers while preserving the named volume.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --instance-id)
      INSTANCE_ID="$2"
      shift 2
      ;;
    --image-ref|--image)
      OPENCLAW_IMAGE="$2"
      shift 2
      ;;
    --version)
      TARGET_VERSION="$2"
      shift 2
      ;;
    --gateway-bind)
      OPENCLAW_GATEWAY_BIND="$2"
      shift 2
      ;;
    --env-file)
      ENV_BASE_FILE="$2"
      shift 2
      ;;
    --env-file=*)
      ENV_BASE_FILE="${1#*=}"
      shift
      ;;
    --db-path)
      DB_PATH="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown parameter: $1"
      ;;
  esac
done

[[ -n "$INSTANCE_ID" ]] || fail "--instance-id is required"

have docker || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
PYTHON_BIN="$(resolve_python_bin)"
[[ -f "$PY_DB_SCRIPT" ]] || fail "instance_db.py not found in $ROOT_DIR"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)_update.log"
exec > >(tee -a "$LOG_FILE") 2>&1

INSTANCE_JSON="$("$PYTHON_BIN" "$PY_DB_SCRIPT" --db "$DB_PATH" get --id "$INSTANCE_ID")"

getj() {
  local key="$1"
  echo "$INSTANCE_JSON" | "$PYTHON_BIN" -c "import sys, json; d=json.load(sys.stdin).get('instance', {}); print(d.get('$key',''))"
}

project_name="$(getj project_name)"
volume_name="$(getj volume_name)"
gateway_port="$(getj gateway_port)"
bridge_port="$(getj bridge_port)"
gateway_token="$(getj token)"
openrouter_token="$(getj openrouter_token)"
telegram_bot_token="$(getj channel_bot_token)"
telegram_allow_from="$(getj allow_from)"
current_version="$(getj version)"
stored_gateway_bind="$(getj gateway_bind)"

[[ -n "$project_name" ]] || fail "project_name missing in DB for instance $INSTANCE_ID"
[[ -n "$volume_name" ]] || fail "volume_name missing in DB for instance $INSTANCE_ID"
[[ -n "$gateway_port" ]] || fail "gateway_port missing in DB for instance $INSTANCE_ID"
[[ -n "$bridge_port" ]] || fail "bridge_port missing in DB for instance $INSTANCE_ID"
[[ -n "$gateway_token" ]] || fail "token missing in DB for instance $INSTANCE_ID"
[[ -n "$openrouter_token" ]] || fail "openrouter_token missing in DB for instance $INSTANCE_ID"

tagify() {
  echo "${1:-latest}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9_.-]/-/g' \
    | sed 's/-\+/-/g' \
    | sed 's/^-//' \
    | sed 's/-$//'
}

normalize_version() {
  local raw="${1:-}"
  if [[ "$raw" =~ [0-9]{4}\.[0-9]+\.[0-9]+([-+._][A-Za-z0-9]+)* ]]; then
    echo "${BASH_REMATCH[0]}"
    return
  fi
  echo "$raw"
}

has_explicit_image_tag() {
  local ref="${1:-}"
  [[ -n "$ref" ]] || return 1
  [[ "$ref" == *"@"* ]] && return 0
  [[ "${ref##*/}" == *:* ]]
}

resolve_local_image_ref() {
  local requested="${1:-}"
  local candidate=""
  local candidates=()
  local image_id=""

  [[ -n "$requested" ]] || return 1

  candidates+=("$requested")
  if ! has_explicit_image_tag "$requested"; then
    candidates+=("${requested}:latest")
  fi

  for candidate in "${candidates[@]}"; do
    image_id="$(docker image ls --format '{{.ID}}' "$candidate" 2>/dev/null | head -n 1)"
    if [[ -n "$image_id" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

if [[ -z "$OPENCLAW_GATEWAY_BIND" ]]; then
  OPENCLAW_GATEWAY_BIND="${stored_gateway_bind:-lan}"
fi

if [[ -z "$OPENCLAW_IMAGE" ]]; then
  OPENCLAW_IMAGE="$(getj image)"
fi

if [[ -z "$OPENCLAW_IMAGE" ]]; then
  OPENCLAW_IMAGE="$DEFAULT_OPENCLAW_IMAGE"
fi

OPENCLAW_RUNTIME_IMAGE="$(resolve_local_image_ref "$OPENCLAW_IMAGE")" || \
  fail "Docker image kullanilabilir degil: $OPENCLAW_IMAGE"

env_file="$(mktemp "$ROOT_DIR/.env.openclaw.update.XXXXXX")"
record_manual_operation_log() {
  if [[ "${OPENCLAW_SKIP_SELF_LOG:-}" == "1" ]]; then
    return 0
  fi
  [[ -n "$LOG_FILE" ]] || return 0
  OPENCLAW_DB_PATH="$DB_PATH" "$PYTHON_BIN" "$MANUAL_OPS_HELPER" record-log \
    --action-type manual-update \
    --log-file-path "$LOG_FILE" \
    --status "$manual_log_status" \
    --instance-id "$INSTANCE_ID" >/dev/null 2>&1 || true
}

cleanup() {
  local exit_code=$?
  rm -f "$env_file" || true
  if [[ "$exit_code" -eq 0 ]]; then
    manual_log_status="success"
  else
    manual_log_status="error"
  fi
  record_manual_operation_log
  exit "$exit_code"
}
trap cleanup EXIT

cat > "$env_file" <<EOF
OPENCLAW_HOME_VOLUME=$volume_name
OPENCLAW_GATEWAY_TOKEN=$gateway_token
OPENCLAW_GATEWAY_PORT=$gateway_port
OPENCLAW_BRIDGE_PORT=$bridge_port
OPENCLAW_GATEWAY_BIND=$OPENCLAW_GATEWAY_BIND
OPENCLAW_IMAGE=$OPENCLAW_RUNTIME_IMAGE
OPENROUTER_API_KEY=$openrouter_token
EOF

if [[ -n "$telegram_bot_token" && -n "$telegram_allow_from" ]]; then
  cat >> "$env_file" <<EOF
TELEGRAM_BOT_TOKEN=$telegram_bot_token
TELEGRAM_ALLOW_FROM=$telegram_allow_from
EOF
fi

compose_cmd=(docker compose -p "$project_name" --env-file "$env_file")

echo "Stopping old services (preserve volume)"
"${compose_cmd[@]}" down --remove-orphans || true

echo "Starting updated services with image: $OPENCLAW_IMAGE"
if [[ "$OPENCLAW_RUNTIME_IMAGE" != "$OPENCLAW_IMAGE" ]]; then
  echo "Resolved runtime image ref: $OPENCLAW_RUNTIME_IMAGE"
fi
"${compose_cmd[@]}" up -d --remove-orphans --force-recreate

effective_version="$(docker run --rm "$OPENCLAW_RUNTIME_IMAGE" openclaw --version 2>/dev/null | head -n 1 | tr -d '\r')"
if [[ -z "$effective_version" ]]; then
  effective_version="${TARGET_VERSION:-$current_version}"
fi
effective_version="$(normalize_version "$effective_version")"

"$PYTHON_BIN" "$PY_DB_SCRIPT" --db "$DB_PATH" update_runtime \
  --id "$INSTANCE_ID" \
  --version "$effective_version" \
  --image "$OPENCLAW_IMAGE" >/dev/null
OPENCLAW_DB_PATH="$DB_PATH" "$PYTHON_BIN" "$MANUAL_OPS_HELPER" sync-instance-container --instance-id "$INSTANCE_ID" >/dev/null

echo "Update completed"
echo "  project : $project_name"
echo "  volume  : $volume_name"
echo "  ports   : $gateway_port, $bridge_port"
echo "  Web Dashboard UI : http://127.0.0.1:$gateway_port/#token=$gateway_token"
