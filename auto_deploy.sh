#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_BASE_FILE="${OPENCLAW_ENV_BASE_FILE:-$ROOT_DIR/env.base}"
DEPLOY_SCRIPT="${OPENCLAW_DEPLOY_SCRIPT:-$ROOT_DIR/deploy_openclaw.sh}"

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

BASE_NAME="${BASE_NAME:-v}"
START_INDEX="${START_INDEX:-4}"
END_INDEX="${END_INDEX:-10}"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_ALLOW_FROM="${TELEGRAM_ALLOW_FROM:-}"
OPENCLAW_GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-}"
DRY_RUN=0

usage() {
  cat <<EOF
Usage:
  $0 [options]
  $0 BASE_NAME OPENROUTER_API_KEY [END_INDEX]

Bulk-deploy OpenClaw instances by invoking deploy_openclaw.sh in a loop.

Options:
  --base-name VALUE            Domain prefix / instance prefix. Default: ${BASE_NAME}
  --start-index N              First index to deploy. Default: ${START_INDEX}
  --end-index N                Last index to deploy. Default: ${END_INDEX}
  --count N                    Number of instances to deploy starting from --start-index
  --openrouter-api-key VALUE   OpenRouter API key. Defaults to env.base / environment
  --gateway-bind VALUE         Forwarded to deploy_openclaw.sh
  --image-ref VALUE            Forwarded to deploy_openclaw.sh as --image-ref
  --gateway-token VALUE        Forwarded to deploy_openclaw.sh
  --telegram-bot-token VALUE   Forwarded to deploy_openclaw.sh
  --telegram-allow-from VALUE  Forwarded to deploy_openclaw.sh
  --env-file PATH              Load defaults from a specific env file
  --deploy-script PATH         Override deploy_openclaw.sh path
  --dry-run                    Print commands without executing them
  -h, --help                   Show this help

Examples:
  $0 --base-name bot --start-index 1 --end-index 5 --openrouter-api-key or-v1-xxx
  $0 bot or-v1-xxx 12
EOF
}

positionals=()
count_override=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-name)
      BASE_NAME="$2"
      shift 2
      ;;
    --start-index)
      START_INDEX="$2"
      shift 2
      ;;
    --end-index)
      END_INDEX="$2"
      shift 2
      ;;
    --count)
      count_override="$2"
      shift 2
      ;;
    --openrouter-api-key)
      OPENROUTER_API_KEY="$2"
      shift 2
      ;;
    --gateway-bind)
      OPENCLAW_GATEWAY_BIND="$2"
      shift 2
      ;;
    --image-ref|--image)
      OPENCLAW_IMAGE="$2"
      shift 2
      ;;
    --gateway-token)
      OPENCLAW_GATEWAY_TOKEN="$2"
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
    --env-file)
      ENV_BASE_FILE="$2"
      shift 2
      ;;
    --env-file=*)
      ENV_BASE_FILE="${1#*=}"
      shift
      ;;
    --deploy-script)
      DEPLOY_SCRIPT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        positionals+=("$1")
        shift
      done
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

if [[ ${#positionals[@]} -gt 3 ]]; then
  echo "Too many positional arguments." >&2
  usage >&2
  exit 1
fi

if [[ ${#positionals[@]} -ge 1 ]]; then
  BASE_NAME="${positionals[0]}"
fi
if [[ ${#positionals[@]} -ge 2 ]]; then
  OPENROUTER_API_KEY="${positionals[1]}"
fi
if [[ ${#positionals[@]} -ge 3 ]]; then
  END_INDEX="${positionals[2]}"
fi

if [[ -n "$count_override" ]]; then
  END_INDEX=$((START_INDEX + count_override - 1))
fi

[[ -n "$BASE_NAME" ]] || { echo "BASE_NAME is required." >&2; usage >&2; exit 1; }
[[ -n "$OPENROUTER_API_KEY" ]] || { echo "OPENROUTER_API_KEY is required." >&2; usage >&2; exit 1; }
[[ -x "$DEPLOY_SCRIPT" ]] || { echo "Deploy script not executable: $DEPLOY_SCRIPT" >&2; exit 1; }
[[ "$START_INDEX" =~ ^[0-9]+$ ]] || { echo "--start-index must be numeric." >&2; exit 1; }
[[ "$END_INDEX" =~ ^[0-9]+$ ]] || { echo "--end-index must be numeric." >&2; exit 1; }
(( END_INDEX >= START_INDEX )) || { echo "--end-index must be >= --start-index." >&2; exit 1; }

for ((i = START_INDEX; i <= END_INDEX; i++)); do
  domain="${BASE_NAME}${i}"
  cmd=(
    "$DEPLOY_SCRIPT"
    --domain "$domain"
    --openrouter-api-key "$OPENROUTER_API_KEY"
  )

  if [[ -n "$OPENCLAW_GATEWAY_BIND" ]]; then
    cmd+=(--gateway-bind "$OPENCLAW_GATEWAY_BIND")
  fi
  if [[ -n "$OPENCLAW_IMAGE" ]]; then
    cmd+=(--image-ref "$OPENCLAW_IMAGE")
  fi
  if [[ -n "$OPENCLAW_GATEWAY_TOKEN" ]]; then
    cmd+=(--gateway-token "$OPENCLAW_GATEWAY_TOKEN")
  fi
  if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
    cmd+=(--telegram-bot-token "$TELEGRAM_BOT_TOKEN")
  fi
  if [[ -n "$TELEGRAM_ALLOW_FROM" ]]; then
    cmd+=(--telegram-allow-from "$TELEGRAM_ALLOW_FROM")
  fi

  echo "--------------------------------------"
  echo "Deploying instance $i -> $domain"
  echo "--------------------------------------"
  printf 'Command:'
  printf ' %q' "${cmd[@]}"
  printf '\n'

  if [[ "$DRY_RUN" -eq 0 ]]; then
    "${cmd[@]}"
  fi
done

echo "All deployments completed."
