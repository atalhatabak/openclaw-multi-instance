#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/openclaw/openclaw.git"
TARGET_DIR="openclaw"
TARGET_FILE="ui/src/ui/storage.ts"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_PATH="$ROOT_DIR/Dockerfile"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-xenv2-openclaw}"

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

load_settings_block_old = """    const parsedGatewayUrl =
      typeof parsed.gatewayUrl === "string" && parsed.gatewayUrl.trim()
        ? parsed.gatewayUrl.trim()
        : defaults.gatewayUrl;
    const gatewayUrl = parsedGatewayUrl === pageDerivedUrl ? defaultUrl : parsedGatewayUrl;
"""

load_settings_block_new = """    const queryUrl = getGatewayUrlFromQuery();
    const parsedGatewayUrl =
      typeof parsed.gatewayUrl === "string" && parsed.gatewayUrl.trim()
        ? parsed.gatewayUrl.trim()
        : defaults.gatewayUrl;
    const gatewayUrl = queryUrl ?? (parsedGatewayUrl === pageDerivedUrl ? defaultUrl : parsedGatewayUrl);
"""

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

if load_settings_block_new in text:
    print("[INFO] loadSettings query override bloğu zaten guncel.")
else:
    if load_settings_block_old not in text:
        print("[ERROR] loadSettings gatewayUrl bloğu bulunamadı.")
        sys.exit(1)

    text = text.replace(load_settings_block_old, load_settings_block_new, 1)
    print("[INFO] loadSettings query override bloğu guncellendi.")
    changed = True

if changed:
    file_path.write_text(text, encoding="utf-8")
    print("[INFO] Dosya güncellendi.")
else:
    print("[INFO] Dosyada değişiklik yapılmadı.")
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
    -t "$OPENCLAW_IMAGE" \
    -f "$DOCKERFILE_PATH" \
    "$source_dir"
}

main() {
  clone_if_needed

  cd "$TARGET_DIR"
  pull_safely
  patch_file "$TARGET_FILE"
  build_image "$PWD"

  log "Tamamlandı."
  log "Kontrol için:"
  log "  cd $TARGET_DIR"
  log "  git diff -- $TARGET_FILE"
  log "  docker image inspect $OPENCLAW_IMAGE"
  log "  git status"
}

main "$@"
