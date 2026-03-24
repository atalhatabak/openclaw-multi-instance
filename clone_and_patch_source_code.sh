#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/openclaw/openclaw.git"
TARGET_DIR="openclaw"
TARGET_FILE="ui/src/ui/storage.ts"

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
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
text = file_path.read_text(encoding="utf-8")

function_block = """function getGatewayUrlFromQuery(): string | null {
  try {
    const params = new URLSearchParams(location.search);
    const raw = params.get("url")?.trim();
    if (!raw) return null;

    const base = `${location.protocol}//${location.host}`;
    const parsed = new URL(raw, base);

    if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
      return null;
    }

    return parsed.toString();
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

changed = False

if "function getGatewayUrlFromQuery(): string | null {" in text:
    print("[INFO] getGatewayUrlFromQuery fonksiyonu zaten mevcut.")
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

if changed:
    file_path.write_text(text, encoding="utf-8")
    print("[INFO] Dosya güncellendi.")
else:
    print("[INFO] Dosyada değişiklik yapılmadı.")
PY
}

main() {
  clone_if_needed

  cd "$TARGET_DIR"
  pull_safely
  patch_file "$TARGET_FILE"

  log "Tamamlandı."
  log "Kontrol için:"
  log "  cd $TARGET_DIR"
  log "  git diff -- $TARGET_FILE"
  log "  git status"
}

main "$@"