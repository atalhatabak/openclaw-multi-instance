#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/openclaw/openclaw.git"
EXTERNAL_OPENCLAW_IMAGE="${OPENCLAW_IMAGE-}"
EXTERNAL_OPENCLAW_TARGET_VERSION="${OPENCLAW_TARGET_VERSION-}"

ENV_BASE_FILE="./env.base"
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


TARGET_DIR="openclaw"
TARGET_FILE="ui/src/ui/storage.ts"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_PATH="$ROOT_DIR/Dockerfile"
WORKTREE_DIR=""

OVERLAY_SOURCE_DIR="$ROOT_DIR/scripts/docker"

log() {
  printf '[INFO] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1" >&2
}

err() {
  printf '[ERROR] %s\n' "$1" >&2
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "'$1' komutu bulunamadı."
    exit 1
  }
}

require_cmd git
require_cmd python3
require_cmd docker

cleanup() {
  if [[ -n "${WORKTREE_DIR:-}" ]]; then
    git -C "$ROOT_DIR/$TARGET_DIR" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

resolve_target_version() {
  python3 - <<'PY'
from services.openclaw_release_service import get_target_stable_version

print(get_target_stable_version())
PY
}

prepare_repo_tags() {
  log "Release tag bilgileri aliniyor..."
  git -C "$ROOT_DIR/$TARGET_DIR" fetch --force --tags origin
}

create_release_worktree() {
  local target_version="$1"
  local tag_ref="refs/tags/v${target_version}"
  local temp_dir

  temp_dir="$(mktemp -d "$ROOT_DIR/.openclaw-build.XXXXXX")"
  rmdir "$temp_dir"
  git -C "$ROOT_DIR/$TARGET_DIR" worktree add --detach "$temp_dir" "$tag_ref" >/dev/null
  printf '%s\n' "$temp_dir"
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

  python3 - "$file" <<'PY'
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

  python3 - "$repo_dir" <<'PY'
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


main() {
  local target_version=""

  clone_if_needed
  prepare_repo_tags

  target_version="$(resolve_target_version)"
  [[ -n "$target_version" ]] || {
    err "Stabil OpenClaw versiyonu belirlenemedi."
    exit 1
  }

  log "Stabil release secildi: $target_version"
  WORKTREE_DIR="$(create_release_worktree "$target_version")"

  patch_file "$WORKTREE_DIR/$TARGET_FILE"
  patch_bundled_channel_entries "$WORKTREE_DIR"
  sync_overlay_files "$WORKTREE_DIR"
  build_image "$WORKTREE_DIR"
  built_version="$(detect_image_version || true)"

  log "Tamamlandı."
  if [ -n "${built_version:-}" ]; then
    log "  version    : $built_version"
  fi
  log "  release    : $target_version"
  log "Kontrol için:"
  log "  git -C $TARGET_DIR show v$target_version --stat --oneline -1"
  log "  docker image inspect $OPENCLAW_IMAGE"
}

main "$@"
