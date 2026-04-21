#!/usr/bin/env sh
set -eu

HOME_DIR="${OPENCLAW_TEMPLATE_HOME:-/home/node}"
OPENCLAW_HOME_DIR="${OPENCLAW_HOME:-/opt/openclaw-home-template}"
GATEWAY_MODE="${OPENCLAW_TEMPLATE_GATEWAY_MODE:-local}"
TOOLS_PROFILE="${OPENCLAW_TEMPLATE_TOOLS_PROFILE:-coding}"
PRIMARY_MODEL="${OPENCLAW_TEMPLATE_PRIMARY_MODEL:-openrouter/xiaomi/mimo-v2-flash}"
PRIMARY_FALLBACK="${OPENCLAW_TEMPLATE_PRIMARY_FALLBACK:-openrouter/xiaomi/mimo-v2-pro}"
IMAGE_MODEL="${OPENCLAW_TEMPLATE_IMAGE_MODEL:-openrouter/xiaomi/mimo-v2-omni}"
IMAGE_FALLBACK="${OPENCLAW_TEMPLATE_IMAGE_FALLBACK:-openrouter/moonshotai/kimi-k2.5}"
BROWSER_ENABLED="${OPENCLAW_TEMPLATE_BROWSER_ENABLED:-true}"
EXEC_SECURITY="${OPENCLAW_TEMPLATE_EXEC_SECURITY:-full}"
EXEC_ASK="${OPENCLAW_TEMPLATE_EXEC_ASK:-off}"
SEARCH_PROVIDER="${OPENCLAW_TEMPLATE_SEARCH_PROVIDER:-duckduckgo}"
BROWSER_PATH_OVERRIDE="${OPENCLAW_TEMPLATE_BROWSER_PATH:-}"
BROWSER_HEADLESS="${OPENCLAW_TEMPLATE_BROWSER_HEADLESS:-true}"
BROWSER_NO_SANDBOX="${OPENCLAW_TEMPLATE_BROWSER_NO_SANDBOX:-true}"
BROWSER_PROFILE="${OPENCLAW_TEMPLATE_BROWSER_PROFILE:-openclaw}"

usage() {
  cat <<EOF
Usage:
  $0 [options]

Prepare the default OpenClaw home template used in the Docker image.

Options:
  --home PATH                 HOME value to use. Default: ${HOME_DIR}
  --openclaw-home PATH        OPENCLAW_HOME value. Default: ${OPENCLAW_HOME_DIR}
  --gateway-mode VALUE        gateway.mode config. Default: ${GATEWAY_MODE}
  --tools-profile VALUE       tools.profile config. Default: ${TOOLS_PROFILE}
  --model VALUE               Primary model. Default: ${PRIMARY_MODEL}
  --model-fallback VALUE      Primary model fallback. Default: ${PRIMARY_FALLBACK}
  --image-model VALUE         Image model. Default: ${IMAGE_MODEL}
  --image-fallback VALUE      Image model fallback. Default: ${IMAGE_FALLBACK}
  --browser-enabled VALUE     browser.enabled. Default: ${BROWSER_ENABLED}
  --exec-security VALUE       tools.exec.security. Default: ${EXEC_SECURITY}
  --exec-ask VALUE            tools.exec.ask. Default: ${EXEC_ASK}
  --search-provider VALUE     tools.web.search.provider. Default: ${SEARCH_PROVIDER}
  --browser-path PATH         Explicit browser executable path
  --browser-headless VALUE    browser.headless. Default: ${BROWSER_HEADLESS}
  --browser-no-sandbox VALUE  browser.noSandbox. Default: ${BROWSER_NO_SANDBOX}
  --browser-profile VALUE     browser.defaultProfile. Default: ${BROWSER_PROFILE}
  -h, --help                  Show this help

Example:
  $0 --model openrouter/xiaomi/mimo-v2-flash --browser-enabled true
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --home)
      HOME_DIR="$2"
      shift 2
      ;;
    --openclaw-home)
      OPENCLAW_HOME_DIR="$2"
      shift 2
      ;;
    --gateway-mode)
      GATEWAY_MODE="$2"
      shift 2
      ;;
    --tools-profile)
      TOOLS_PROFILE="$2"
      shift 2
      ;;
    --model)
      PRIMARY_MODEL="$2"
      shift 2
      ;;
    --model-fallback)
      PRIMARY_FALLBACK="$2"
      shift 2
      ;;
    --image-model)
      IMAGE_MODEL="$2"
      shift 2
      ;;
    --image-fallback)
      IMAGE_FALLBACK="$2"
      shift 2
      ;;
    --browser-enabled)
      BROWSER_ENABLED="$2"
      shift 2
      ;;
    --exec-security)
      EXEC_SECURITY="$2"
      shift 2
      ;;
    --exec-ask)
      EXEC_ASK="$2"
      shift 2
      ;;
    --search-provider)
      SEARCH_PROVIDER="$2"
      shift 2
      ;;
    --browser-path)
      BROWSER_PATH_OVERRIDE="$2"
      shift 2
      ;;
    --browser-headless)
      BROWSER_HEADLESS="$2"
      shift 2
      ;;
    --browser-no-sandbox)
      BROWSER_NO_SANDBOX="$2"
      shift 2
      ;;
    --browser-profile)
      BROWSER_PROFILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

export HOME="$HOME_DIR"
export OPENCLAW_HOME="$OPENCLAW_HOME_DIR"

/usr/local/bin/openclaw config set gateway.mode "$GATEWAY_MODE" >/dev/null
/usr/local/bin/openclaw config set tools.profile "$TOOLS_PROFILE" >/dev/null
/usr/local/bin/openclaw models set "$PRIMARY_MODEL" >/dev/null
/usr/local/bin/openclaw models fallbacks add "$PRIMARY_FALLBACK"

/usr/local/bin/openclaw models set-image "$IMAGE_MODEL"
/usr/local/bin/openclaw models fallbacks add "$IMAGE_FALLBACK"

/usr/local/bin/openclaw config set browser.enabled "$BROWSER_ENABLED" >/dev/null
/usr/local/bin/openclaw config set tools.exec.security "$EXEC_SECURITY" >/dev/null
/usr/local/bin/openclaw config set tools.exec.ask "$EXEC_ASK" >/dev/null
/usr/local/bin/openclaw config set tools.web.search.provider "$SEARCH_PROVIDER"

BROWSER_PATH="$BROWSER_PATH_OVERRIDE"
if [ -z "$BROWSER_PATH" ]; then
  BROWSER_PATH="$(find /home/node/.cache/ms-playwright -path '*/chrome-linux64/chrome' | head -n 1)"
fi
if [ -n "$BROWSER_PATH" ]; then
  /usr/local/bin/openclaw config set browser.executablePath "$BROWSER_PATH" >/dev/null
fi

/usr/local/bin/openclaw config set browser.headless "$BROWSER_HEADLESS" >/dev/null
/usr/local/bin/openclaw config set browser.noSandbox "$BROWSER_NO_SANDBOX" >/dev/null
/usr/local/bin/openclaw config set browser.defaultProfile "$BROWSER_PROFILE" >/dev/null
