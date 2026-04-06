#!/usr/bin/env bash
set -euo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_BASE_FILE="${OPENCLAW_ENV_BASE_FILE:-$ROOT_DIR/env.base}"
if [[ -f "$ENV_BASE_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_BASE_FILE"
  set +a
fi

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
PY_DB_SCRIPT="$ROOT_DIR/instance_db.py"
DB_PATH="${OPENCLAW_DB_PATH:-$ROOT_DIR/openclaw_instances.db}"
LOCK_FILE="${OPENCLAW_LOCK_FILE:-$ROOT_DIR/.openclaw_deploy.lock}"

LOG_DIR="${OPENCLAW_LOG_DIR:-$ROOT_DIR/logs/deploy}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%dT%H%M%SZ)_deploy.log"
exec > >(tee -a "$LOG_FILE") 2>&1

DOMAIN="${DOMAIN:-}"
VERSION="${OPENCLAW_CURRENT_IMAGE_VERSION:-2026.4.3}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_ALLOW_FROM="${TELEGRAM_ALLOW_FROM:-}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
OPENCLAW_GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-claw}"
OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-lan}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-xenv1-openclaw:latest}"
CHANNEL_CHOICE="web"

usage() {
  cat <<EOF
Usage:
  $0 \
    [--domain mebs.claw] \
    [--image-ref xenv1-openclaw:latest] \
    [--telegram-bot-token 123456:ABCDEF] \
    [--telegram-allow-from 905551112233] \
    [--openrouter-api-key or-v1-xxxxx] \
    [--gateway-token my-token] \
    [--version latest] \
    [--gateway-bind lan]

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
have python3 || fail "python3 is not installed"
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found in $ROOT_DIR"
[[ -f "$PY_DB_SCRIPT" ]] || fail "instance_db.py not found in $ROOT_DIR"
# have flock || fail "flock is not installed"

python3 "$PY_DB_SCRIPT" --db "$DB_PATH" init >/dev/null

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

random_token() {
  if have openssl; then
    openssl rand -hex 24
  else
    python3 - <<'PY'
import secrets
print(secrets.token_hex(24))
PY
  fi
}

cleanup_needed=1
env_file=""
volume_created=0
compose_started=0
project_name=""
volume_name=""
gateway_port=""
bridge_port=""
compose_cmd=()

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
  fi

  exit "$exit_code"
}
trap cleanup EXIT

# exec 9>"$LOCK_FILE"
# flock -x 9

PORTS_JSON="$(python3 "$PY_DB_SCRIPT" --db "$DB_PATH" available_port --base-gateway 20000 --step 2)"
gateway_port="$(echo "$PORTS_JSON" | python3 -c 'import sys, json; print(json.load(sys.stdin)["gateway_port"])')"
bridge_port="$(echo "$PORTS_JSON" | python3 -c 'import sys, json; print(json.load(sys.stdin)["bridge_port"])')"

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

cat > "$env_file" <<EOF
OPENCLAW_HOME_VOLUME=$volume_name
OPENCLAW_GATEWAY_TOKEN=$OPENCLAW_GATEWAY_TOKEN
OPENCLAW_GATEWAY_PORT=$gateway_port
OPENCLAW_BRIDGE_PORT=$bridge_port
OPENCLAW_GATEWAY_BIND=$OPENCLAW_GATEWAY_BIND
OPENCLAW_IMAGE=$OPENCLAW_IMAGE
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

: "${OPENCLAW_HOME_VOLUME:?missing}"
: "${OPENCLAW_GATEWAY_PORT:?missing}"
: "${OPENCLAW_BRIDGE_PORT:?missing}"
: "${OPENCLAW_GATEWAY_BIND:?missing}"
: "${OPENCLAW_IMAGE:?missing}"
: "${OPENROUTER_API_KEY:?missing}"

docker image inspect "$OPENCLAW_IMAGE" >/dev/null 2>&1 || \
  fail "Docker image bulunamadi: $OPENCLAW_IMAGE. Once clone_and_patch_source_code.sh ile image hazirla."

echo "Using prebuilt OpenClaw image: $OPENCLAW_IMAGE"

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

python3 "$PY_DB_SCRIPT" --db "$DB_PATH" add \
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
  --image "$OPENCLAW_IMAGE" >/dev/null

rm -f "$env_file"
env_file=""
cleanup_needed=0
trap - EXIT

echo "Created instance successfully"
echo "  domain  : $DOMAIN"
echo "  key     : $instance_key"
echo "  project : $project_name"
echo "  volume  : $volume_name"
echo "  ports   : $gateway_port, $bridge_port"
echo "  Web Dashboard UI : http://127.0.0.1:$gateway_port/#token=$OPENCLAW_GATEWAY_TOKEN"
