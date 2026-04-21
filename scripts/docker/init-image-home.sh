#!/usr/bin/env sh
set -eu

TEMPLATE_ROOT="${OPENCLAW_TEMPLATE_ROOT:-/opt/openclaw-home-template/.openclaw}"
TARGET_ROOT="${OPENCLAW_TARGET_ROOT:-/home/node/.openclaw}"
MARKER_FILE="${OPENCLAW_IMAGE_MARKER_FILE:-}"
GATEWAY_BIND_VALUE="${OPENCLAW_GATEWAY_BIND:-}"
DOMAIN_VALUE="${DOMAIN:-}"
TELEGRAM_BOT_TOKEN_VALUE="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_ALLOW_FROM_VALUE="${TELEGRAM_ALLOW_FROM:-}"
ENABLE_TELEGRAM_CONFIG=0
CONFIGURE_GATEWAY_SETTINGS=1
SEED_ONLY=0

usage() {
  cat <<EOF
Usage:
  $0 [options] [-- command args...]

Seed /home/node/.openclaw from the image template and optionally configure gateway settings.

Options:
  --template-root PATH         Source template directory. Default: ${TEMPLATE_ROOT}
  --target-root PATH           Destination OpenClaw home. Default: ${TARGET_ROOT}
  --marker-file PATH           Marker file used to avoid reseeding. Default: TARGET_ROOT/.image-seeded-v1
  --gateway-bind VALUE         Configure gateway.bind
  --domain VALUE               Configure gateway.controlUi.allowedOrigins
  --telegram-bot-token VALUE   Telegram bot token reference
  --telegram-allow-from VALUE  Telegram allowlist entry
  --enable-telegram            Apply Telegram channel configuration too
  --disable-gateway-config     Skip gateway/control UI configuration
  --seed-only                  Seed/configure and exit without exec'ing a command
  -h, --help                   Show this help

Examples:
  $0 --domain example.com -- node openclaw.mjs gateway --allow-unconfigured
  $0 --seed-only --template-root /tmp/template
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --template-root)
      TEMPLATE_ROOT="$2"
      shift 2
      ;;
    --target-root)
      TARGET_ROOT="$2"
      shift 2
      ;;
    --marker-file)
      MARKER_FILE="$2"
      shift 2
      ;;
    --gateway-bind)
      GATEWAY_BIND_VALUE="$2"
      shift 2
      ;;
    --domain)
      DOMAIN_VALUE="$2"
      shift 2
      ;;
    --telegram-bot-token)
      TELEGRAM_BOT_TOKEN_VALUE="$2"
      shift 2
      ;;
    --telegram-allow-from)
      TELEGRAM_ALLOW_FROM_VALUE="$2"
      shift 2
      ;;
    --enable-telegram)
      ENABLE_TELEGRAM_CONFIG=1
      shift
      ;;
    --disable-gateway-config)
      CONFIGURE_GATEWAY_SETTINGS=0
      shift
      ;;
    --seed-only)
      SEED_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [ -z "$MARKER_FILE" ]; then
  MARKER_FILE="$TARGET_ROOT/.image-seeded-v1"
fi

copy_template() {
  mkdir -p "$TARGET_ROOT"
  if [ -d "$TEMPLATE_ROOT" ]; then
    cp -R "$TEMPLATE_ROOT"/. "$TARGET_ROOT"/
  fi
}

configure_gateway() {
  if [ "$CONFIGURE_GATEWAY_SETTINGS" != "1" ]; then
    return 0
  fi

  if [ -n "$GATEWAY_BIND_VALUE" ]; then
    /usr/local/bin/openclaw config set gateway.bind "$GATEWAY_BIND_VALUE" >/dev/null
  fi

  if [ -n "$DOMAIN_VALUE" ]; then
    /usr/local/bin/openclaw config set gateway.controlUi.allowedOrigins "[\"https://${DOMAIN_VALUE}\",\"http://127.0.0.1\"]" --strict-json >/dev/null
  fi
}

configure_telegram() {
  if [ "$ENABLE_TELEGRAM_CONFIG" != "1" ]; then
    return 0
  fi

  if [ -n "$TELEGRAM_BOT_TOKEN_VALUE" ] && [ -n "$TELEGRAM_ALLOW_FROM_VALUE" ]; then
    export TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN_VALUE"
    /usr/local/bin/openclaw config set channels.telegram.enabled true >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.botToken \
      --ref-provider default \
      --ref-source env \
      --ref-id TELEGRAM_BOT_TOKEN >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.dmPolicy allowlist >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.allowFrom "[\"${TELEGRAM_ALLOW_FROM_VALUE}\"]" --strict-json >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.groupAllowFrom "[\"${TELEGRAM_ALLOW_FROM_VALUE}\"]" --strict-json >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.groupPolicy allowlist >/dev/null
    /usr/local/bin/openclaw config set channels.telegram.streaming partial >/dev/null
  fi
}

if [ ! -f "$MARKER_FILE" ] && [ ! -f "$TARGET_ROOT/openclaw.json" ]; then
  copy_template
  configure_gateway
  configure_telegram
  touch "$MARKER_FILE"
elif [ ! -f "$MARKER_FILE" ]; then
  touch "$MARKER_FILE"
fi

if [ "$SEED_ONLY" = "1" ]; then
  exit 0
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
