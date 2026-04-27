#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_URL="https://github.com/openclaw/openclaw.git"
EXTERNAL_OPENCLAW_IMAGE="${OPENCLAW_IMAGE-}"
EXTERNAL_OPENCLAW_TARGET_VERSION="${OPENCLAW_TARGET_VERSION-}"
EXTERNAL_OPENCLAW_SOURCE_MODE="${OPENCLAW_SOURCE_MODE-}"
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

if [[ -n "${EXTERNAL_OPENCLAW_IMAGE:-}" ]]; then
  export OPENCLAW_IMAGE="$EXTERNAL_OPENCLAW_IMAGE"
fi

if [[ -n "${EXTERNAL_OPENCLAW_TARGET_VERSION:-}" ]]; then
  export OPENCLAW_TARGET_VERSION="$EXTERNAL_OPENCLAW_TARGET_VERSION"
fi

if [[ -n "${EXTERNAL_OPENCLAW_SOURCE_MODE:-}" ]]; then
  export OPENCLAW_SOURCE_MODE="$EXTERNAL_OPENCLAW_SOURCE_MODE"
fi


TARGET_DIR="${OPENCLAW_SOURCE_DIR:-openclaw}"
TARGET_FILE="${OPENCLAW_TARGET_FILE:-ui/src/ui/storage.ts}"
DOCKERFILE_PATH="${OPENCLAW_DOCKERFILE:-$ROOT_DIR/Dockerfile}"
WORKTREE_DIR=""

OVERLAY_SOURCE_DIR="${OPENCLAW_OVERLAY_SOURCE_DIR:-$ROOT_DIR/scripts/docker}"

log() {
  printf '[INFO] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1" >&2
}

err() {
  printf '[ERROR] %s\n' "$1" >&2
}

usage() {
  cat <<EOF
Usage:
  $0 [options]

Clone/update the upstream OpenClaw repo, apply local patches, and build a Docker image.

Options:
  --image-ref VALUE         Target Docker image ref. Defaults to OPENCLAW_IMAGE
  --source-mode MODE        Source selection: stable|main. Default: stable
  --main                    Shortcut for --source-mode main
  --target-version VALUE    Build a specific OpenClaw version tag
  --repo-url URL            Upstream git repo URL. Default: ${REPO_URL}
  --target-dir DIR          Local upstream checkout directory. Default: ${TARGET_DIR}
  --target-file PATH        File patched by the storage override patch. Default: ${TARGET_FILE}
  --dockerfile PATH         Dockerfile used for the build. Default: ${DOCKERFILE_PATH}
  --overlay-source-dir DIR  Directory containing helper overlay scripts. Default: ${OVERLAY_SOURCE_DIR}
  --env-file PATH           Load defaults from a specific env file
  --force-rebuild           Build even if the target image/version already exists locally
  --no-force-rebuild        Disable forced rebuild
  -h, --help                Show this help

Examples:
  $0 --image-ref xen-v2026.4.15 --target-version 2026.4.15
  $0 --source-mode main --image-ref xen-main
  $0 --env-file ./env.base --force-rebuild
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --image-ref|--image)
        export OPENCLAW_IMAGE="$2"
        shift 2
        ;;
      --source-mode)
        export OPENCLAW_SOURCE_MODE="$2"
        shift 2
        ;;
      --main)
        export OPENCLAW_SOURCE_MODE="main"
        shift
        ;;
      --target-version|--version)
        export OPENCLAW_TARGET_VERSION="$2"
        shift 2
        ;;
      --repo-url)
        REPO_URL="$2"
        shift 2
        ;;
      --target-dir)
        TARGET_DIR="$2"
        shift 2
        ;;
      --target-file)
        TARGET_FILE="$2"
        shift 2
        ;;
      --dockerfile)
        DOCKERFILE_PATH="$2"
        shift 2
        ;;
      --overlay-source-dir)
        OVERLAY_SOURCE_DIR="$2"
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
      --force-rebuild)
        export OPENCLAW_FORCE_REBUILD=1
        shift
        ;;
      --no-force-rebuild)
        export OPENCLAW_FORCE_REBUILD=0
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      -*)
        err "Unknown option: $1"
        usage >&2
        exit 1
        ;;
      *)
        err "Unexpected argument: $1"
        usage >&2
        exit 1
        ;;
    esac
  done
}

parse_args "$@"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "'$1' komutu bulunamadı."
    exit 1
  }
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    require_cmd "$PYTHON_BIN"
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return 0
  fi
  err "'python3' veya 'python' komutu bulunamadı."
  exit 1
}

require_cmd git
PYTHON_BIN="$(resolve_python_bin)"
require_cmd docker

cleanup() {
  if [[ -n "${WORKTREE_DIR:-}" ]]; then
    git -C "$ROOT_DIR/$TARGET_DIR" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

normalize_version() {
  local raw="${1:-}"
  if [[ "$raw" =~ ([0-9]{4}\.[0-9]+\.[0-9]+([-+._][A-Za-z0-9]+)*) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi
  printf '%s\n' "$raw"
}

resolve_source_mode() {
  local raw="${OPENCLAW_SOURCE_MODE:-stable}"
  local normalized="${raw,,}"

  case "$normalized" in
    stable|release)
      printf '%s\n' "stable"
      ;;
    main)
      printf '%s\n' "main"
      ;;
    *)
      err "Gecersiz source mode: $raw. Beklenen: stable veya main"
      exit 1
      ;;
  esac
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

detect_image_version_for_ref() {
  local image_ref="${1:-}"
  docker run --rm "$image_ref" openclaw --version 2>/dev/null | head -n 1 | tr -d '\r'
}

should_skip_build() {
  local target_version="$1"
  local normalized_target_version=""
  local existing_image_ref=""
  local existing_version=""
  local force_rebuild="${OPENCLAW_FORCE_REBUILD:-}"

  if [[ -n "$force_rebuild" && "$force_rebuild" != "0" && "${force_rebuild,,}" != "false" ]]; then
    log "OPENCLAW_FORCE_REBUILD etkin, mevcut image olsa bile rebuild zorlanacak."
    return 1
  fi

  existing_image_ref="$(resolve_local_image_ref "$OPENCLAW_IMAGE" || true)"
  if [[ -z "$existing_image_ref" ]]; then
    return 1
  fi

  normalized_target_version="$(normalize_version "$target_version")"
  existing_version="$(normalize_version "$(detect_image_version_for_ref "$existing_image_ref" || true)")"

  if [[ -n "$existing_version" && "$existing_version" == "$normalized_target_version" ]]; then
    log "Hedef image zaten mevcut ve guncel: $existing_image_ref ($existing_version)"
    log "Rebuild atlandi. Zorlamak istersen OPENCLAW_FORCE_REBUILD=1 kullan."
    return 0
  fi

  return 1
}

resolve_target_version() {
  "$PYTHON_BIN" - <<'PY'
from services.openclaw_release_service import get_target_stable_version

print(get_target_stable_version())
PY
}

detect_repo_version_from_dir() {
  local repo_dir="$1"

  "$PYTHON_BIN" - "$repo_dir" <<'PY'
import json
import re
import sys
from pathlib import Path

version_pattern = re.compile(r"\b\d{4}\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*\b")
package_json = Path(sys.argv[1]) / "package.json"

try:
    payload = json.loads(package_json.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    print("")
    raise SystemExit(0)

raw = str(payload.get("version") or "").strip()
match = version_pattern.search(raw)
print(match.group(0) if match else raw)
PY
}

prepare_repo_refs() {
  log "Remote branch ve release tag bilgileri aliniyor..."
  git -C "$ROOT_DIR/$TARGET_DIR" fetch --force --tags origin
}

create_ref_worktree() {
  local source_ref="$1"
  local temp_dir

  temp_dir="$(mktemp -d "$ROOT_DIR/.openclaw-build.XXXXXX")"
  rmdir "$temp_dir"
  git -C "$ROOT_DIR/$TARGET_DIR" worktree add --detach "$temp_dir" "$source_ref" >/dev/null
  printf '%s\n' "$temp_dir"
}

create_release_worktree() {
  local target_version="$1"
  create_ref_worktree "refs/tags/v${target_version}"
}

create_main_worktree() {
  create_ref_worktree "refs/remotes/origin/main"
}

sync_overlay_files() {
  local repo_dir="$1"
  local overlay_target_dir="$repo_dir/scripts/docker"

  if [ ! -d "$OVERLAY_SOURCE_DIR" ]; then
    err "Overlay klasoru bulunamadi: $OVERLAY_SOURCE_DIR"
    exit 1
  fi

  mkdir -p "$overlay_target_dir"

  cp "$OVERLAY_SOURCE_DIR/build-image-template.sh" "$overlay_target_dir/build-image-template.sh"
  cp "$OVERLAY_SOURCE_DIR/init-image-home.sh" "$overlay_target_dir/init-image-home.sh"
  chmod 755 "$overlay_target_dir/build-image-template.sh" "$overlay_target_dir/init-image-home.sh"

  log "Docker helper scriptleri sync edildi: $overlay_target_dir"
}

clone_if_needed() {
  if [ -d "$TARGET_DIR/.git" ]; then
    log "Repo zaten mevcut: $TARGET_DIR"
    return
  fi

  if [ -e "$TARGET_DIR" ] && [ ! -d "$TARGET_DIR/.git" ]; then
    err "'$TARGET_DIR' var ama bir git repo değil. Elle kontrol et."
    exit 1
  fi

  log "Repo clone ediliyor..."
  log "git clone $REPO_URL"
  git clone "$REPO_URL"
}

has_local_changes() {
  git diff --quiet || return 0
  git diff --cached --quiet || return 0
  return 1
}

pull_safely() {
  local stashed=0
  local before after
  local current_branch

  before="$(git rev-parse HEAD)"
  current_branch="$(git rev-parse --abbrev-ref HEAD)"

  if has_local_changes; then
    log "Local değişiklikler bulundu, stash alınıyor..."
    git stash push -u -m "auto-stash-before-update" >/dev/null
    stashed=1
  fi

  log "Remote güncellemeler alınıyor..."
  git fetch origin

  log "Branch güncelleniyor: $current_branch"
  git pull --ff-only origin "$current_branch"

  after="$(git rev-parse HEAD)"

  if [ "$before" = "$after" ]; then
    log "Yeni commit yok."
  else
    log "Yeni commit çekildi: $before -> $after"
  fi

  if [ "$stashed" -eq 1 ]; then
    log "Stash geri uygulanıyor..."
    if ! git stash pop >/dev/null; then
      err "stash pop sırasında conflict oluştu. Elle çözmen gerekiyor."
      err "Durum kontrolü için: git status"
      exit 1
    fi
  fi
}

patch_file() {
  local file="$1"

  if [ ! -f "$file" ]; then
    err "Dosya bulunamadı: $file"
    exit 1
  fi

  "$PYTHON_BIN" - "$file" <<'PY'
import re
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
text = file_path.read_text(encoding="utf-8")

function_block = """function getGatewayUrlFromQuery(): string | null {
  try {
    const params = new URLSearchParams(location.search);
    const raw = params.get("url")?.trim();
    if (!raw) return null;

    let portSuffix = "";

    if (/^\\d{4}$/.test(raw)) {
      portSuffix = raw;
    } else if (/^2\\d{4}$/.test(raw)) {
      portSuffix = raw.slice(1);
    } else {
      const base = `${location.protocol}//${location.host}`;
      const parsed = new URL(raw, base);

      if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
        return null;
      }

      if (!/^2\\d{4}$/.test(parsed.port)) {
        return null;
      }

      portSuffix = parsed.port.slice(1);
    }

    return `ws://127.0.0.1:2${portSuffix}`;
  } catch {
    return null;
  }
}
"""

function_anchor = """function deriveDefaultGatewayUrl(): { pageUrl: string; effectiveUrl: string } {
"""

insert_after = """  const pageUrl = `${proto}://${location.host}${basePath}`;
"""

query_block = """  const queryUrl = getGatewayUrlFromQuery();
  if (queryUrl) {
    return { pageUrl, effectiveUrl: queryUrl };
  }
"""

query_line = "    const queryUrl = getGatewayUrlFromQuery();\n"
gateway_line_old = "    const gatewayUrl = parsedGatewayUrl === pageDerivedUrl ? defaultUrl : parsedGatewayUrl;\n"
gateway_line_new = (
    "    const gatewayUrl = queryUrl ?? "
    "(parsedGatewayUrl === pageDerivedUrl ? defaultUrl : parsedGatewayUrl);\n"
)

changed = False
function_pattern = re.compile(
    r"function getGatewayUrlFromQuery\(\): string \| null \{\n(?:.*?\n)\}\n",
    re.DOTALL,
)

match = function_pattern.search(text)
if match:
    existing_function = match.group(0)
    if existing_function == function_block:
        print("[INFO] getGatewayUrlFromQuery fonksiyonu zaten guncel.")
    else:
        text = text[:match.start()] + function_block + text[match.end():]
        print("[INFO] getGatewayUrlFromQuery fonksiyonu guncellendi.")
        changed = True
else:
    if function_anchor not in text:
        print("[ERROR] deriveDefaultGatewayUrl fonksiyon anchor'ı bulunamadı.")
        sys.exit(1)

    text = text.replace(function_anchor, function_block + "\n" + function_anchor, 1)
    print("[INFO] getGatewayUrlFromQuery fonksiyonu eklendi.")
    changed = True

if query_block in text:
    print("[INFO] queryUrl override bloğu zaten mevcut.")
else:
    if insert_after not in text:
        print("[ERROR] pageUrl satırı bulunamadı.")
        sys.exit(1)

    text = text.replace(insert_after, insert_after + "\n" + query_block, 1)
    print("[INFO] queryUrl override bloğu eklendi.")
    changed = True

if gateway_line_new in text:
    print("[INFO] loadSettings query override bloğu zaten guncel.")
else:
    lines = text.splitlines(keepends=True)
    gateway_index = next((i for i, line in enumerate(lines) if line == gateway_line_old), None)
    if gateway_index is None:
        print("[ERROR] loadSettings gatewayUrl satırı bulunamadı.")
        sys.exit(1)

    parsed_index = gateway_index - 1
    while parsed_index >= 0 and "const parsedGatewayUrl" not in lines[parsed_index]:
        parsed_index -= 1
    if parsed_index < 0:
        print("[ERROR] loadSettings parsedGatewayUrl satırı bulunamadı.")
        sys.exit(1)

    if parsed_index == 0 or lines[parsed_index - 1] != query_line:
        lines.insert(parsed_index, query_line)
        gateway_index += 1

    lines[gateway_index] = gateway_line_new
    text = "".join(lines)
    print("[INFO] loadSettings query override bloğu guncellendi.")
    changed = True

if changed:
    file_path.write_text(text, encoding="utf-8")
    print("[INFO] Dosya güncellendi.")
else:
    print("[INFO] Dosyada değişiklik yapılmadı.")
PY
}

patch_bundled_channel_entries() {
  local repo_dir="$1"

  "$PYTHON_BIN" - "$repo_dir" <<'PY'
from pathlib import Path
import sys

repo_dir = Path(sys.argv[1])

files = {
    repo_dir / "extensions" / "mattermost" / "index.ts": (
        'specifier: "./src/channel.js"',
        'specifier: "./channel-plugin-api.js"',
    ),
    repo_dir / "extensions" / "mattermost" / "setup-entry.ts": (
        'specifier: "./src/channel.js"',
        'specifier: "./channel-plugin-api.js"',
    ),
}

for path, (old, new) in files.items():
    if not path.exists():
        print(f"[ERROR] Dosya bulunamadi: {path}")
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"[INFO] Zaten guncel: {path}")
        continue
    if old not in text:
        print(f"[ERROR] Beklenen icerik bulunamadi: {path}")
        sys.exit(1)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[INFO] Guncellendi: {path}")

mattermost_api = repo_dir / "extensions" / "mattermost" / "channel-plugin-api.ts"
mattermost_api_content = """// Keep bundled channel entry imports narrow so bootstrap/discovery paths do
// not drag the full Mattermost API barrel into lightweight plugin loads.
export { mattermostPlugin } from "./src/channel.js";
"""
if mattermost_api.exists():
    existing = mattermost_api.read_text(encoding="utf-8")
    if existing == mattermost_api_content:
        print(f"[INFO] Zaten guncel: {mattermost_api}")
    else:
        mattermost_api.write_text(mattermost_api_content, encoding="utf-8")
        print(f"[INFO] Guncellendi: {mattermost_api}")
else:
    mattermost_api.write_text(mattermost_api_content, encoding="utf-8")
    print(f"[INFO] Eklendi: {mattermost_api}")

qa_setup = repo_dir / "extensions" / "qa-channel" / "setup-entry.ts"
qa_setup_content = """import { defineBundledChannelSetupEntry } from "openclaw/plugin-sdk/channel-entry-contract";

export default defineBundledChannelSetupEntry({
  importMetaUrl: import.meta.url,
  plugin: {
    specifier: "./api.js",
    exportName: "qaChannelPlugin",
  },
});
"""
if not qa_setup.exists():
    print(f"[ERROR] Dosya bulunamadi: {qa_setup}")
    sys.exit(1)
existing_qa = qa_setup.read_text(encoding="utf-8")
if existing_qa == qa_setup_content:
    print(f"[INFO] Zaten guncel: {qa_setup}")
else:
    qa_setup.write_text(qa_setup_content, encoding="utf-8")
    print(f"[INFO] Guncellendi: {qa_setup}")
PY
}

build_image() {
  local source_dir="$1"

  if [ ! -d "$source_dir" ]; then
    err "Kaynak klasoru bulunamadi: $source_dir"
    exit 1
  fi

  if [ ! -f "$DOCKERFILE_PATH" ]; then
    err "Dockerfile bulunamadi: $DOCKERFILE_PATH"
    exit 1
  fi

  log "OpenClaw image build basliyor..."
  log "  source dir : $source_dir"
  log "  dockerfile : $DOCKERFILE_PATH"
  log "  image      : $OPENCLAW_IMAGE"

  DOCKER_BUILDKIT=1 docker build \
    --progress=plain \
    -t "$OPENCLAW_IMAGE" \
    -f "$DOCKERFILE_PATH" \
    "$source_dir"
}

detect_image_version() {
  docker run --rm "$OPENCLAW_IMAGE" openclaw --version 2>/dev/null | head -n 1 | tr -d '\r'
}

register_managed_image() {
  local image_ref="$1"
  local image_version="$2"
  local version_source="$3"

  [[ -n "$image_ref" ]] || return 1
  [[ -n "$image_version" ]] || return 1

  "$PYTHON_BIN" - "$image_ref" "$image_version" "$version_source" <<'PY'
import sys

import db
from models import managed_image_model

image_ref = sys.argv[1].strip()
image_version = sys.argv[2].strip()
version_source = sys.argv[3].strip() or "manual"

db.init_db()
managed_image_model.upsert_managed_image(
    image_ref=image_ref,
    version=image_version,
    version_source=version_source,
)
PY
}


main() {
  local source_mode=""
  local target_version=""
  local source_ref_label=""
  local source_commit=""
  local resolved_image_ref=""
  local built_version=""
  local managed_version=""
  local managed_version_source=""

  clone_if_needed
  prepare_repo_refs
  source_mode="$(resolve_source_mode)"

  case "$source_mode" in
    stable)
      target_version="$(resolve_target_version)"
      [[ -n "$target_version" ]] || {
        err "Stabil OpenClaw versiyonu belirlenemedi."
        exit 1
      }
      source_ref_label="v${target_version}"

      if [[ -z "${OPENCLAW_IMAGE:-}" ]]; then
        export OPENCLAW_IMAGE="xen-v${target_version}"
        log "OPENCLAW_IMAGE tanimli degildi, varsayilan image ref secildi: $OPENCLAW_IMAGE"
      fi

      log "Stabil release secildi: $target_version"
      if should_skip_build "$target_version"; then
        resolved_image_ref="$(resolve_local_image_ref "$OPENCLAW_IMAGE" || true)"
        if [[ -n "$resolved_image_ref" ]]; then
          built_version="$(detect_image_version_for_ref "$resolved_image_ref" || true)"
        fi
        managed_version="$(normalize_version "${built_version:-$target_version}")"
        managed_version_source="release-stable"
        if register_managed_image "$OPENCLAW_IMAGE" "$managed_version" "$managed_version_source"; then
          log "Image kaydi DB'ye yazildi: $OPENCLAW_IMAGE | $managed_version | $managed_version_source"
        fi

        log "Tamamlandı."
        if [ -n "${built_version:-}" ]; then
          log "  version    : $built_version"
        fi
        log "  source     : stable ($source_ref_label)"
        log "Kontrol için:"
        log "  docker image inspect $OPENCLAW_IMAGE"
        return 0
      fi

      WORKTREE_DIR="$(create_release_worktree "$target_version")"
      ;;
    main)
      if [[ -n "${OPENCLAW_TARGET_VERSION:-}" ]]; then
        warn "OPENCLAW_TARGET_VERSION main modunda yok sayiliyor."
      fi

      WORKTREE_DIR="$(create_main_worktree)"
      source_commit="$(git -C "$WORKTREE_DIR" rev-parse HEAD)"
      source_ref_label="origin/main@${source_commit:0:12}"
      target_version="$(detect_repo_version_from_dir "$WORKTREE_DIR")"
      [[ -n "$target_version" ]] || target_version="main-${source_commit:0:12}"

      if [[ -z "${OPENCLAW_IMAGE:-}" ]]; then
        export OPENCLAW_IMAGE="xen-main-${source_commit:0:12}"
        log "OPENCLAW_IMAGE tanimli degildi, varsayilan main image ref secildi: $OPENCLAW_IMAGE"
      fi

      log "Main branch secildi: $source_ref_label"
      log "Main modunda surum ayni kalsa bile commit degisebilecegi icin rebuild atlanmayacak."
      ;;
  esac

  patch_file "$WORKTREE_DIR/$TARGET_FILE"
  patch_bundled_channel_entries "$WORKTREE_DIR"
  sync_overlay_files "$WORKTREE_DIR"
  build_image "$WORKTREE_DIR"
  built_version="$(detect_image_version || true)"
  managed_version="$(normalize_version "${built_version:-$target_version}")"
  managed_version_source="release-stable"
  if [[ "$source_mode" == "main" ]]; then
    managed_version_source="main"
  fi
  if register_managed_image "$OPENCLAW_IMAGE" "$managed_version" "$managed_version_source"; then
    log "Image kaydi DB'ye yazildi: $OPENCLAW_IMAGE | $managed_version | $managed_version_source"
  fi

  log "Tamamlandı."
  if [ -n "${built_version:-}" ]; then
    log "  version    : $built_version"
  fi
  log "  source     : $source_mode ($source_ref_label)"
  log "Kontrol için:"
  if [[ "$source_mode" == "stable" ]]; then
    log "  git -C $TARGET_DIR show v$target_version --stat --oneline -1"
  else
    log "  git -C $TARGET_DIR log origin/main -1 --oneline"
  fi
  log "  docker image inspect $OPENCLAW_IMAGE"
}

main "$@"
