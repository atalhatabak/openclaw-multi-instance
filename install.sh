#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

EXAMPLE_ENV_FILE="$ROOT_DIR/env.base"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
BASE_PORT=20010

fail() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

if [ -f "InstanceNumber" ]; then
    INSTANCE_NUMBER=$(<InstanceNumber)
    INSTANCE_NUMBER=$((INSTANCE_NUMBER + 1))
else
    INSTANCE_NUMBER=1
fi

# ---- 4) Generate gateway token ----
have openssl || fail "openssl is not installed"
OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"

PROJECT_NAME="openclaw-instance-$INSTANCE_NUMBER"
VOLUME_NAME="openclaw-volume-$INSTANCE_NUMBER"
ENV_FILE=".env.$INSTANCE_NUMBER"
cp "$EXAMPLE_ENV_FILE" "$ENV_FILE"
OPENCLAW_GATEWAY_PORT=$((BASE_PORT + (INSTANCE_NUMBER - 1) * 2))
OPENCLAW_BRIDGE_PORT=$((OPENCLAW_GATEWAY_PORT + 1))

cat >> "$ENV_FILE" <<EOF
OPENCLAW_HOME_VOLUME=$VOLUME_NAME
OPENCLAW_GATEWAY_TOKEN=$OPENCLAW_GATEWAY_TOKEN
OPENCLAW_GATEWAY_PORT=$OPENCLAW_GATEWAY_PORT
OPENCLAW_BRIDGE_PORT=$OPENCLAW_BRIDGE_PORT
EOF

# ---- 1) Prerequisites ----
have docker || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found in $ROOT_DIR"
[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE not found in $ROOT_DIR"

# ---- 2) Load .env (export all vars inside) ----
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ---- 3) Validate required variables ----
: "${OPENCLAW_HOME_VOLUME:?OPENCLAW_HOME_VOLUME is required in .env}"
: "${OPENCLAW_GATEWAY_PORT:=20000}"
: "${OPENCLAW_BRIDGE_PORT:=20001}"
: "${OPENCLAW_GATEWAY_BIND:=lan}"
: "${OPENCLAW_IMAGE:=ghcr.io/openclaw/openclaw:latest}"

# Build extended image

echo "Building custom OpenClaw image..."
DOCKER_BUILDKIT=1 docker build --pull -t atalhatabak/openclaw-extras:latest .

# ---- 5) Create named volume (idempotent) ----
docker volume inspect "$OPENCLAW_HOME_VOLUME" >/dev/null 2>&1 || \
  docker volume create "$OPENCLAW_HOME_VOLUME" >/dev/null
echo "Volume ready: $OPENCLAW_HOME_VOLUME"

# CONFIG 
COMPOSE="docker compose -p $PROJECT_NAME --env-file $ENV_FILE"

# dizin yetkisi veriyoruz
$COMPOSE run --rm --user root --entrypoint sh openclaw-cli -c \
  'find /home/node/.openclaw -xdev -exec chown node:node {} +; \
   [ -d /home/node/.openclaw/workspace/.openclaw ] && chown -R node:node /home/node/.openclaw/workspace/.openclaw || true'

# openclaw.json edit for browser and coder profile
$COMPOSE run --rm --entrypoint sh openclaw-cli -c "
  echo 'config setting: gateway mode/bind/allowed-origins'
  /usr/local/bin/openclaw config set gateway.mode local 
  /usr/local/bin/openclaw config set gateway.bind $OPENCLAW_GATEWAY_BIND 
  /usr/local/bin/openclaw config set gateway.controlUi.allowedOrigins '[\"http://localhost:'"${OPENCLAW_GATEWAY_PORT}"'\",\"http://127.0.0.1:'"${OPENCLAW_GATEWAY_PORT}"'\"]' --strict-json 
  echo 'Profile change with coding, Onboard starting'
  /usr/local/bin/openclaw config set tools.profile coding 
  /usr/local/bin/openclaw onboard --accept-risk --flow quickstart --skip-skills --skip-ui --skip-channels  --skip-daemon --auth-choice apiKey --token-provider openrouter --token $OPENROUTER_API_KEY 
  echo 'Model, browser channels config'
  /usr/local/bin/openclaw models set openrouter/stepfun/step-3.5-flash:free 
  /usr/local/bin/openclaw config set browser.enabled true 
  /usr/local/bin/openclaw config set browser.executablePath /usr/bin/google-chrome 
  /usr/local/bin/openclaw config set browser.headless true 
  /usr/local/bin/openclaw config set browser.noSandbox true 
  /usr/local/bin/openclaw config set browser.defaultProfile openclaw 
  /usr/local/bin/openclaw browser start
  /usr/local/bin/openclaw config set channels.telegram.enabled true 
  /usr/local/bin/openclaw config set channels.telegram.botToken $TELEGRAM_BOT_TOKEN 
  /usr/local/bin/openclaw config set channels.telegram.dmPolicy allowlist 
  /usr/local/bin/openclaw config set channels.telegram.allowFrom [\"$TELEGRAM_ALLOW_FROM\"] --strict-json 
  /usr/local/bin/openclaw config set channels.telegram.groupAllowFrom [\"$TELEGRAM_ALLOW_FROM\"] --strict-json 
  /usr/local/bin/openclaw config set channels.telegram.groupPolicy allowlist 
  /usr/local/bin/openclaw config set channels.telegram.streaming partial 
  echo 'probably all done .d'
"

# ---- 6) Pull image & start gateway ----
echo "Starting services"
$COMPOSE  up -d

# Update Instance Number
echo "$INSTANCE_NUMBER"  > InstanceNumber

echo "Created $ENV_FILE"
echo "  instance: $INSTANCE_NUMBER"
echo "  project : $PROJECT_NAME"
echo "  volume  : $VOLUME_NAME"
echo "  ports   : $OPENCLAW_GATEWAY_PORT, $OPENCLAW_BRIDGE_PORT"
echo "  Web Dashboard UI   : http://127.0.0.1:$OPENCLAW_GATEWAY_PORT/#token=$OPENCLAW_GATEWAY_TOKEN"