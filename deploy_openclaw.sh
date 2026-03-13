#!/usr/bin/env bash
set -euo pipefail

fail() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
PY_DB_SCRIPT="$ROOT_DIR/instance_db.py"
DB_PATH="${OPENCLAW_DB_PATH:-$ROOT_DIR/openclaw_instances.db}"
LOCK_FILE="${OPENCLAW_LOCK_FILE:-$ROOT_DIR/.openclaw_deploy.lock}"

DOMAIN=""
VERSION="latest"
TELEGRAM_BOT_TOKEN=""
TELEGRAM_ALLOW_FROM=""
OPENROUTER_API_KEY=""
OPENCLAW_GATEWAY_TOKEN=""
OPENCLAW_IMAGE="ghcr.io/openclaw/openclaw:latest"
OPENCLAW_GATEWAY_BIND="lan"
CHANNEL_CHOICE="telegram"

usage() {
  cat <<EOF
Usage:
  $0 \
    --domain example.com \
    --telegram-bot-token 123456:ABCDEF \
    --telegram-allow-from 905551112233 \
    --openrouter-api-key or-v1-xxxxx \
    [--gateway-token my-token] \
    [--version latest] \
    [--image ghcr.io/openclaw/openclaw:latest] \
    [--gateway-bind lan]

Notes:
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
    --image)
      OPENCLAW_IMAGE="$2"
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

[[ -n "$DOMAIN" ]] || fail "--domain is required"
[[ -n "$TELEGRAM_BOT_TOKEN" ]] || fail "--telegram-bot-token is required"
[[ -n "$TELEGRAM_ALLOW_FROM" ]] || fail "--telegram-allow-from is required"
[[ -n "$OPENROUTER_API_KEY" ]] || fail "--openrouter-api-key is required"

have docker || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
have python3 || fail "python3 is not installed"
# have flock || fail "flock is not installed"
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found in $ROOT_DIR"
[[ -f "$PY_DB_SCRIPT" ]] || fail "instance_db.py not found in $ROOT_DIR"

python3 "$PY_DB_SCRIPT" --db "$DB_PATH" init >/dev/null

slugify() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9]/-/g' \
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
project_name="openclaw-${domain_slug}-${gateway_port}"
volume_name="openclaw-volume-${domain_slug}-${gateway_port}"

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
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_ALLOW_FROM=$TELEGRAM_ALLOW_FROM
EOF

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${OPENCLAW_HOME_VOLUME:?missing}"
: "${OPENCLAW_GATEWAY_PORT:?missing}"
: "${OPENCLAW_BRIDGE_PORT:?missing}"
: "${OPENCLAW_GATEWAY_BIND:?missing}"
: "${OPENCLAW_IMAGE:?missing}"
: "${OPENROUTER_API_KEY:?missing}"
: "${TELEGRAM_BOT_TOKEN:?missing}"
: "${TELEGRAM_ALLOW_FROM:?missing}"

echo "Building custom OpenClaw image..."

DOCKER_BUILDKIT=1 docker build -t atalhatabak/openclaw-extras:latest .

docker volume inspect "$OPENCLAW_HOME_VOLUME" >/dev/null 2>&1 || {
  docker volume create "$OPENCLAW_HOME_VOLUME" >/dev/null
  volume_created=1
}
echo "Volume ready: $OPENCLAW_HOME_VOLUME"

compose_cmd=(docker compose -p "$project_name" --env-file "$env_file")

"${compose_cmd[@]}" run --rm --user root --entrypoint sh openclaw-cli -c \
  'find /home/node/.openclaw -xdev -exec chown node:node {} +; \
   [ -d /home/node/.openclaw/workspace/.openclaw ] && chown -R node:node /home/node/.openclaw/workspace/.openclaw || true'

"${compose_cmd[@]}" run --rm --entrypoint sh openclaw-cli -c "
  echo 'config setting: gateway mode/bind/allowed-origins'
  /usr/local/bin/openclaw config set gateway.mode local
  /usr/local/bin/openclaw config set gateway.bind $OPENCLAW_GATEWAY_BIND
  /usr/local/bin/openclaw config set gateway.controlUi.allowedOrigins '[\"http://localhost:${OPENCLAW_GATEWAY_PORT}\",\"http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}\"]' --strict-json

  echo 'Profile change with coding, Onboard starting'
  /usr/local/bin/openclaw config set tools.profile coding
  /usr/local/bin/openclaw onboard --non-interactive --accept-risk --flow quickstart --gateway-auth token --gateway-token $OPENCLAW_GATEWAY_TOKEN --skip-channels --skip-daemon --skip-skills --skip-ui --auth-choice apiKey --token-provider openrouter --token $OPENROUTER_API_KEY

  echo 'Model, browser channels config'
  /usr/local/bin/openclaw models set openrouter/stepfun/step-3.5-flash:free
  /usr/local/bin/openclaw config set browser.enabled true
  /usr/local/bin/openclaw config set browser.executablePath /usr/bin/google-chrome
  /usr/local/bin/openclaw config set browser.headless true
  /usr/local/bin/openclaw config set browser.noSandbox true
  /usr/local/bin/openclaw config set browser.defaultProfile openclaw

  /usr/local/bin/openclaw config set channels.telegram.enabled true
  /usr/local/bin/openclaw config set channels.telegram.botToken $TELEGRAM_BOT_TOKEN
  /usr/local/bin/openclaw config set channels.telegram.dmPolicy allowlist
  /usr/local/bin/openclaw config set channels.telegram.allowFrom [\"$TELEGRAM_ALLOW_FROM\"] --strict-json
  /usr/local/bin/openclaw config set channels.telegram.groupAllowFrom [\"$TELEGRAM_ALLOW_FROM\"] --strict-json
  /usr/local/bin/openclaw config set channels.telegram.groupPolicy allowlist
  /usr/local/bin/openclaw config set channels.telegram.streaming partial

  echo 'probably all done'
"

echo "Starting services"
"${compose_cmd[@]}" up -d
compose_started=1

python3 "$PY_DB_SCRIPT" --db "$DB_PATH" add \
  --domain "$DOMAIN" \
  --project-name "$project_name" \
  --volume-name "$volume_name" \
  --gateway-port "$gateway_port" \
  --bridge-port "$bridge_port" \
  --version "$VERSION" \
  --channel-choice "$CHANNEL_CHOICE" \
  --channel-bot-token "$TELEGRAM_BOT_TOKEN" \
  --allow-from "$TELEGRAM_ALLOW_FROM" \
  --token "$OPENCLAW_GATEWAY_TOKEN" \
  --openrouter-token "$OPENROUTER_API_KEY" >/dev/null

rm -f "$env_file"
env_file=""
cleanup_needed=0
trap - EXIT

echo "Created instance successfully"
echo "  domain  : $DOMAIN"
echo "  project : $project_name"
echo "  volume  : $volume_name"
echo "  ports   : $gateway_port, $bridge_port"
echo "  Web Dashboard UI : http://127.0.0.1:$gateway_port/#token=$OPENCLAW_GATEWAY_TOKEN"