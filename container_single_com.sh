#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

START_INDEX="${START_INDEX:-1}"
END_INDEX="${END_INDEX:-31}"
BASE_PORT="${BASE_PORT:-20000}"
PORT_STEP="${PORT_STEP:-2}"
CONTAINER_TEMPLATE="${CONTAINER_TEMPLATE:-openclaw-bot{index}-mebsclaw-com-{port}-openclaw-gateway-1}"
OPENROUTER_KEY="${OPENROUTER_KEY:-${OPENROUTER_API_KEY:-}}"
RESTART_FIRST=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage:
  $0 [options]

Run \`openclaw onboard\` inside a batch of gateway containers.

Options:
  --start-index N                First container index. Default: ${START_INDEX}
  --end-index N                  Last container index. Default: ${END_INDEX}
  --base-port N                  Base gateway port. Default: ${BASE_PORT}
  --port-step N                  Port increment per instance. Default: ${PORT_STEP}
  --container-template TEMPLATE  Name template with {index} and {port} placeholders
  --openrouter-api-key VALUE     API key used by \`openclaw onboard\`
  --restart                      Restart each container before onboard
  --dry-run                      Print commands without executing them
  --env-file PATH                Load defaults from a specific env file
  -h, --help                     Show this help

Example:
  $0 --start-index 1 --end-index 5 --openrouter-api-key or-v1-xxx
EOF
}

render_container_name() {
  local template="$1"
  local index="$2"
  local port="$3"
  local rendered="${template//\{index\}/$index}"
  rendered="${rendered//\{port\}/$port}"
  printf '%s\n' "$rendered"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-index)
      START_INDEX="$2"
      shift 2
      ;;
    --end-index)
      END_INDEX="$2"
      shift 2
      ;;
    --base-port)
      BASE_PORT="$2"
      shift 2
      ;;
    --port-step)
      PORT_STEP="$2"
      shift 2
      ;;
    --container-template)
      CONTAINER_TEMPLATE="$2"
      shift 2
      ;;
    --openrouter-api-key|--openrouter-key)
      OPENROUTER_KEY="$2"
      shift 2
      ;;
    --restart)
      RESTART_FIRST=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --env-file)
      ENV_BASE_FILE="$2"
      shift 2
      ;;
    --env-file=*)
      ENV_BASE_FILE="${1#*=}"
      shift
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

[[ -n "$OPENROUTER_KEY" ]] || { echo "OPENROUTER API key is required." >&2; usage >&2; exit 1; }
[[ "$START_INDEX" =~ ^[0-9]+$ ]] || { echo "--start-index must be numeric." >&2; exit 1; }
[[ "$END_INDEX" =~ ^[0-9]+$ ]] || { echo "--end-index must be numeric." >&2; exit 1; }
[[ "$BASE_PORT" =~ ^[0-9]+$ ]] || { echo "--base-port must be numeric." >&2; exit 1; }
[[ "$PORT_STEP" =~ ^[0-9]+$ ]] || { echo "--port-step must be numeric." >&2; exit 1; }
(( END_INDEX >= START_INDEX )) || { echo "--end-index must be >= --start-index." >&2; exit 1; }

for ((i = START_INDEX; i <= END_INDEX; i++)); do
  port=$((BASE_PORT + i * PORT_STEP))
  container="$(render_container_name "$CONTAINER_TEMPLATE" "$i" "$port")"

  echo ">>> $container"

  restart_cmd=(docker restart "$container")
  onboard_cmd=(
    docker exec -i "$container"
    openclaw onboard --non-interactive --accept-risk
    --openrouter-api-key "$OPENROUTER_KEY"
  )

  if [[ "$RESTART_FIRST" -eq 1 ]]; then
    printf 'Restart command:'
    printf ' %q' "${restart_cmd[@]}"
    printf '\n'
    if [[ "$DRY_RUN" -eq 0 ]]; then
      "${restart_cmd[@]}"
    fi
  fi

  printf 'Onboard command:'
  printf ' %q' "${onboard_cmd[@]}"
  printf '\n'
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "${onboard_cmd[@]}"
  fi
done
