#!/usr/bin/env sh
set -eu

TEMPLATE_ROOT="/opt/openclaw-home-template/.openclaw"
TARGET_ROOT="/home/node/.openclaw"
MARKER_FILE="$TARGET_ROOT/.image-seeded-v1"

copy_template() {
  mkdir -p "$TARGET_ROOT"
  if [ -d "$TEMPLATE_ROOT" ]; then
    cp -R "$TEMPLATE_ROOT"/. "$TARGET_ROOT"/
  fi
}

configure_gateway() {
  if [ -n "${OPENCLAW_GATEWAY_BIND:-}" ]; then
    /usr/local/bin/openclaw config set gateway.bind "$OPENCLAW_GATEWAY_BIND" >/dev/null
  fi

  if [ -n "${DOMAIN:-}" ]; then
    /usr/local/bin/openclaw config set gateway.controlUi.allowedOrigins "[\"https://${DOMAIN}\"]" --strict-json >/dev/null
  fi
}

configure_telegram() {
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_ALLOW_FROM:-}" ]; then
    /usr/local/bin/openclaw config set channels.telegram.enabled true >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.botToken \
      --ref-provider default \
      --ref-source env \
      --ref-id TELEGRAM_BOT_TOKEN >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.dmPolicy allowlist >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.allowFrom "[\"${TELEGRAM_ALLOW_FROM}\"]" --strict-json >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.groupAllowFrom "[\"${TELEGRAM_ALLOW_FROM}\"]" --strict-json >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.groupPolicy allowlist >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.streaming partial >/dev/null
  fi
}

if [ ! -f "$MARKER_FILE" ] && [ ! -f "$TARGET_ROOT/openclaw.json" ]; then
  copy_template
  configure_gateway
  # configure_telegram
  touch "$MARKER_FILE"
elif [ ! -f "$MARKER_FILE" ]; then
  touch "$MARKER_FILE"
fi

exec "$@"
