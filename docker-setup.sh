#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

fail() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- 1) Prerequisites ----
have docker || fail "docker is not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose is not available"
[[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found in $ROOT_DIR"
[[ -f "$ENV_FILE" ]] || fail ".env not found in $ROOT_DIR"

# ---- 2) Load .env (export all vars inside) ----
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# ---- 3) Validate required variables ----
: "${OPENCLAW_HOME_VOLUME:?OPENCLAW_HOME_VOLUME is required in .env}"
: "${OPENCLAW_GATEWAY_PORT:=18789}"
: "${OPENCLAW_BRIDGE_PORT:=18790}"
: "${OPENCLAW_GATEWAY_BIND:=lan}"
: "${OPENCLAW_IMAGE:=ghcr.io/openclaw/openclaw:latest}"

# ---- 4) Ensure gateway token exists (generate if missing) ----
if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  if have openssl; then
    OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"
  else
    OPENCLAW_GATEWAY_TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi

  # write token back to .env (append or replace)
  if grep -q '^OPENCLAW_GATEWAY_TOKEN=' "$ENV_FILE"; then
    # macOS/Linux compatible replace
    tmp="$(mktemp)"
    awk -v tok="$OPENCLAW_GATEWAY_TOKEN" '
      BEGIN{done=0}
      /^OPENCLAW_GATEWAY_TOKEN=/{print "OPENCLAW_GATEWAY_TOKEN=" tok; done=1; next}
      {print}
      END{ if(!done) print "OPENCLAW_GATEWAY_TOKEN=" tok }
    ' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf '\nOPENCLAW_GATEWAY_TOKEN=%s\n' "$OPENCLAW_GATEWAY_TOKEN" >> "$ENV_FILE"
  fi

  export OPENCLAW_GATEWAY_TOKEN
  echo "Generated OPENCLAW_GATEWAY_TOKEN and saved into .env"
fi

# ---- 5) Create named volume (idempotent) ----
docker volume inspect "$OPENCLAW_HOME_VOLUME" >/dev/null 2>&1 || \
  docker volume create "$OPENCLAW_HOME_VOLUME" >/dev/null
echo "Volume ready: $OPENCLAW_HOME_VOLUME"

## geçici konteyner açarak volume(disk) üzerinde işlem yapıyoruz

# dizin yetkisi veriyoruz
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file .env run --rm --user root --entrypoint sh openclaw-cli -c \
  'find /home/node/.openclaw -xdev -exec chown node:node {} +; \
   [ -d /home/node/.openclaw/workspace/.openclaw ] && chown -R node:node /home/node/.openclaw/workspace/.openclaw || true'

# gateway mod ve bind ayarlıyoruz
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file .env run --rm openclaw-cli \
  config set gateway.mode local >/dev/null

docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file .env run --rm openclaw-cli \
    config set gateway.bind "$OPENCLAW_GATEWAY_BIND" >/dev/null

# bind lan olduğundan giriş yapabilmek için allowedorigins ekliyoruz
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file .env run  --rm openclaw-cli \
  config set gateway.controlUi.allowedOrigins \
  "[\"http://localhost:${OPENCLAW_GATEWAY_PORT}\",\"http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}\"]" --strict-json >/dev/null

#Modeli Ayarlama
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file .env run --rm openclaw-cli \
    models set openrouter/stepfun/step-3.5-flash:free >/dev/null


# ---- 6) Pull image & start gateway ----
echo "Pulling image: $OPENCLAW_IMAGE"
docker compose  -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE"  pull

echo "Starting services"
docker compose  -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE"  up -d

# ---- 7) Pin basic gateway config ----
# (Assumes you have a service named "openclaw-cli" in compose, like upstream.)
echo "Setting gateway.mode=local"
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE" run --rm openclaw-cli \
  config set gateway.mode local >/dev/null

echo "Setting gateway.bind=$OPENCLAW_GATEWAY_BIND"
docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE" run --rm openclaw-cli \
  config set gateway.bind "$OPENCLAW_GATEWAY_BIND" >/dev/null

# ---- 8) Ensure allowedOrigins only when needed ----
if [[ "$OPENCLAW_GATEWAY_BIND" != "loopback" ]]; then
  current="$(
    docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE" run --rm openclaw-cli \
      config get gateway.controlUi.allowedOrigins 2>/dev/null || true
  )"
  current="${current//$'\r'/}"

  if [[ -z "$current" || "$current" == "null" || "$current" == "[]" ]]; then
    # Minimal default allowlist (localhost + 127.0.0.1)
    allowed="$(printf '["http://localhost:%s","http://127.0.0.1:%s"]' "$OPENCLAW_GATEWAY_PORT" "$OPENCLAW_GATEWAY_PORT")"
    docker compose -p "$OPENCLAW_HOME_VOLUME" --env-file "$ENV_FILE" run --rm openclaw-cli \
      config set gateway.controlUi.allowedOrigins "$allowed" --strict-json >/dev/null
    echo "Set gateway.controlUi.allowedOrigins = $allowed"
  else
    echo "allowedOrigins already set; leaving as-is: $current"
  fi
fi

echo ""
echo "Done."
echo "Gateway port: $OPENCLAW_GATEWAY_PORT"
echo "Bridge  port: $OPENCLAW_BRIDGE_PORT"
echo "Bind mode   : $OPENCLAW_GATEWAY_BIND"
echo "Volume      : $OPENCLAW_HOME_VOLUME (mounted to /home/node/.openclaw via compose)"
echo "Token       : $OPENCLAW_GATEWAY_TOKEN"