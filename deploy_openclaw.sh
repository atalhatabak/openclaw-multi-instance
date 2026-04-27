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

COMPOSE_FILE="${OPENCLAW_COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
PY_DB_SCRIPT="$ROOT_DIR/instance_db.py"
MANUAL_OPS_HELPER="$ROOT_DIR/scripts/manual_operation_state.py"
DB_PATH="${OPENCLAW_DB_PATH:-$ROOT_DIR/openclaw_instances.db}"
LOCK_FILE="${OPENCLAW_LOCK_FILE:-$ROOT_DIR/.openclaw_deploy.lock}"

LOG_DIR="${OPENCLAW_LOG_DIR:-$ROOT_DIR/logs/deploy}"
LOG_FILE=""

DOMAIN="${DOMAIN:-}"
VERSION="${OPENCLAW_CURRENT_IMAGE_VERSION:-2026.4.3}"
DEFAULT_OPENCLAW_IMAGE="xen-v${VERSION}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_ALLOW_FROM="${TELEGRAM_ALLOW_FROM:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
OPENCLAW_GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-claw}"
OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-lan}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-$DEFAULT_OPENCLAW_IMAGE}"
CHANNEL_CHOICE="web"

usage() {
  cat <<EOF
Usage:
  $0 [options]

Options:
  --domain VALUE
  --image-ref VALUE
  --telegram-bot-token VALUE
  --telegram-allow-from VALUE
  --openrouter-api-key VALUE
  --gateway-token VALUE
  --version VALUE
  --gateway-bind VALUE
  --env-file PATH
  --db-path PATH
  --log-dir PATH
  --lock-file PATH
  --compose-file PATH
  -h, --help

Notes:
  - Varsayilanlar env.base dosyasindan okunur.
  - Public origin tek domaine sabitlenir: https://DOMAIN
  - Portlar DB'den otomatik alınır.
  - İlk gateway port 20000, bridge port 20001'dir.
  - Her yeni instance 2 port ilerler.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      DOMAIN="$2"
      shift 2
      ;;
    --image-ref|--image)
      OPENCLAW_IMAGE="$2"
      shift 2
      ;;
    --version)
      VERSION="$2"
      shift 2
      ;;
    --telegram-bot-token)
      TELEGRAM_BOT_TOKEN="$2"
      shift 2
      ;;
    --telegram-allow-from)
      TELEGRAM_ALLOW_FROM="$2"
      shift 2
      ;;
    --openrouter-api-key)
      OPENROUTER_API_KEY="$2"
      shift 2
      ;;
    --gateway-token)
      OPENCLAW_GATEWAY_TOKEN="$2"
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
    --lock-file)
      LOCK_FILE="$2"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="$2"
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

[[ -n "$DOMAIN" ]] || fail "DOMAIN env.base icinde veya --domain ile tanimli olmali"
[[ -n "$OPENROUTER_API_KEY" ]] || fail "--openrouter-api-key is required"

have docker || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
PYTHON_BIN="$(resolve_python_bin)"
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found in $ROOT_DIR"
[[ -f "$PY_DB_SCRIPT" ]] || fail "instance_db.py not found in $ROOT_DIR"
# have flock || fail "flock is not installed"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)_deploy.log"
exec > >(tee -a "$LOG_FILE") 2>&1

"$PYTHON_BIN" "$PY_DB_SCRIPT" --db "$DB_PATH" init >/dev/null

slugify() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9]/-/g' \
    | sed 's/-\+/-/g' \
    | sed 's/^-//' \
    | sed 's/-$//'
}

image_tagify() {
  echo "${1:-latest}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9_.-]/-/g' \
    | sed 's/-\+/-/g' \
    | sed 's/^-//' \
    | sed 's/-$//'
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

random_token() {
  if have openssl; then
    openssl rand -hex 24
  else
    "$PYTHON_BIN" - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
  fi
}

cleanup_needed=1
env_file=""
volume_created=0
compose_started=0
instance_created=0
manual_instance_id=""
manual_log_status="error"
project_name=""
volume_name=""
gateway_port=""
bridge_port=""
compose_cmd=()
OPENCLAW_RUNTIME_IMAGE=""

record_manual_operation_log() {
  if [[ "${OPENCLAW_SKIP_SELF_LOG:-}" == "1" ]]; then
    return 0
  fi
  [[ -n "$LOG_FILE" ]] || return 0
  local cmd=(
    "$PYTHON_BIN" "$MANUAL_OPS_HELPER" record-log
    --action-type manual-deploy
    --log-file-path "$LOG_FILE"
    --status "$manual_log_status"
  )
  if [[ -n "$manual_instance_id" ]]; then
    cmd+=(--instance-id "$manual_instance_id")
  fi
  OPENCLAW_DB_PATH="$DB_PATH" "${cmd[@]}" >/dev/null 2>&1 || true
}

cleanup() {
  local exit_code=$?
  if [[ "$cleanup_needed" -eq 1 ]]; then
    echo "Rollback starting..." >&2

    if [[ "$compose_started" -eq 1 && ${#compose_cmd[@]} -gt 0 ]]; then
      "${compose_cmd[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    fi

    if [[ "$volume_created" -eq 1 && -n "$volume_name" ]]; then
      docker volume rm -f "$volume_name" >/dev/null 2>&1 || true
    fi

    if [[ -n "$env_file" && -f "$env_file" ]]; then
      rm -f "$env_file" || true
    fi

    if [[ "$instance_created" -eq 1 && -n "$manual_instance_id" ]]; then
      OPENCLAW_DB_PATH="$DB_PATH" "$PYTHON_BIN" "$MANUAL_OPS_HELPER" purge-instance-records --instance-id "$manual_instance_id" >/dev/null 2>&1 || true
      manual_instance_id=""
    fi
  fi

  if [[ "$exit_code" -eq 0 ]]; then
    manual_log_status="success"
  else
    manual_log_status="error"
  fi
  record_manual_operation_log
  exit "$exit_code"
}
trap cleanup EXIT

# exec 9>"$LOCK_FILE"
# flock -x 9

PORTS_JSON="$("$PYTHON_BIN" "$PY_DB_SCRIPT" --db "$DB_PATH" available_port --base-gateway 20000 --step 2)"
gateway_port="$(echo "$PORTS_JSON" | "$PYTHON_BIN" -c 'import sys, json; print(json.load(sys.stdin)["gateway_port"])')"
bridge_port="$(echo "$PORTS_JSON" | "$PYTHON_BIN" -c 'import sys, json; print(json.load(sys.stdin)["bridge_port"])')"

domain_slug="$(slugify "$DOMAIN")"
instance_key="${DOMAIN}--${gateway_port}"
project_name="openclaw-${gateway_port}"
volume_name="openclaw-volume-${gateway_port}"
OPENCLAW_HOME_VOLUME="$volume_name"
OPENCLAW_GATEWAY_PORT="$gateway_port"
OPENCLAW_BRIDGE_PORT="$bridge_port"

if [[ -z "$OPENCLAW_GATEWAY_TOKEN" ]]; then
#   OPENCLAW_GATEWAY_TOKEN="$(random_token)"
  OPENCLAW_GATEWAY_TOKEN="claw"
fi

env_file="$(mktemp "$ROOT_DIR/.env.openclaw.XXXXXX")"

: "${OPENCLAW_HOME_VOLUME:?missing}"
: "${OPENCLAW_GATEWAY_PORT:?missing}"
: "${OPENCLAW_BRIDGE_PORT:?missing}"
: "${OPENCLAW_GATEWAY_BIND:?missing}"
: "${OPENCLAW_IMAGE:?missing}"
: "${OPENROUTER_API_KEY:?missing}"

OPENCLAW_RUNTIME_IMAGE="$(resolve_local_image_ref "$OPENCLAW_IMAGE")" || \
  fail "Docker image aktif Docker context'inde bulunamadi: $OPENCLAW_IMAGE. Once clone_patch_build.sh ile image hazirla."

echo "Using prebuilt OpenClaw image: $OPENCLAW_IMAGE"
if [[ "$OPENCLAW_RUNTIME_IMAGE" != "$OPENCLAW_IMAGE" ]]; then
  echo "Resolved runtime image ref: $OPENCLAW_RUNTIME_IMAGE"
fi

cat > "$env_file" <<EOF
OPENCLAW_HOME_VOLUME=$volume_name
OPENCLAW_GATEWAY_TOKEN=$OPENCLAW_GATEWAY_TOKEN
OPENCLAW_GATEWAY_PORT=$gateway_port
OPENCLAW_BRIDGE_PORT=$bridge_port
OPENCLAW_GATEWAY_BIND=$OPENCLAW_GATEWAY_BIND
OPENCLAW_IMAGE=$OPENCLAW_RUNTIME_IMAGE
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
DOMAIN=$DOMAIN
EOF

if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_ALLOW_FROM" ]]; then
  cat >> "$env_file" <<EOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_ALLOW_FROM=$TELEGRAM_ALLOW_FROM
EOF
  CHANNEL_CHOICE="telegram"
fi

docker volume inspect "$OPENCLAW_HOME_VOLUME" >/dev/null 2>&1 || {
  docker volume create "$OPENCLAW_HOME_VOLUME" >/dev/null
  volume_created=1
}
echo "Volume ready: $OPENCLAW_HOME_VOLUME"

compose_cmd=(docker compose -p "$project_name" --env-file "$env_file")

"${compose_cmd[@]}" run --rm --no-deps --user root --entrypoint sh openclaw-gateway -c \
  'find /home/node/.openclaw -xdev -exec chown node:node {} +; \
   [ -d /home/node/.openclaw/workspace/.openclaw ] && chown -R node:node /home/node/.openclaw/workspace/.openclaw || true'

echo "Starting services"
"${compose_cmd[@]}" up -d
compose_started=1

# echo "browser starting"

# gateway_container_name=""
# for _ in {1..20}; do
#   gateway_container_name="$(docker ps \
#     --filter "label=com.docker.compose.project=$project_name" \
#     --filter "label=com.docker.compose.service=openclaw-gateway" \
#     --format '{{.Names}}' | head -n 1)"
#   if [[ -n "$gateway_container_name" ]]; then
#     break
#   fi
#   sleep 1
# done
# echo $gateway_container_name
# [[ -n "$gateway_container_name" ]] || fail "openclaw-gateway container name bulunamadi"

# docker exec -i "$gateway_container_name" openclaw browser start

INSTANCE_ADD_JSON="$("$PYTHON_BIN" "$PY_DB_SCRIPT" --db "$DB_PATH" add \
  --domain "$instance_key" \
  --domain-short "$domain_slug" \
  --project-name "$project_name" \
  --volume-name "$volume_name" \
  --gateway-port "$gateway_port" \
  --bridge-port "$bridge_port" \
  --version "$VERSION" \
  --gateway-bind "$OPENCLAW_GATEWAY_BIND" \
  --channel-choice "$CHANNEL_CHOICE" \
  --channel-bot-token "${TELEGRAM_BOT_TOKEN:-}" \
  --allow-from "${TELEGRAM_ALLOW_FROM:-}" \
  --token "$OPENCLAW_GATEWAY_TOKEN" \
  --openrouter-token "$OPENROUTER_API_KEY" \
  --image "$OPENCLAW_IMAGE")"
manual_instance_id="$(printf '%s' "$INSTANCE_ADD_JSON" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["instance"]["id"])')"
instance_created=1

OPENCLAW_DB_PATH="$DB_PATH" "$PYTHON_BIN" "$MANUAL_OPS_HELPER" sync-instance-container --instance-id "$manual_instance_id" >/dev/null

rm -f "$env_file"
env_file=""
cleanup_needed=0

echo "Created instance successfully"
echo "  domain  : $DOMAIN"
echo "  key     : $instance_key"
echo "  project : $project_name"
echo "  volume  : $volume_name"
echo "  ports   : $gateway_port, $bridge_port"
echo "  Web Dashboard UI : http://127.0.0.1:$gateway_port/#token=$OPENCLAW_GATEWAY_TOKEN"
