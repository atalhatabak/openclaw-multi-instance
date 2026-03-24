#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/openclaw/openclaw.git"
TARGET_DIR="openclaw"
TARGET_FILE="ui/src/ui/views/login-gate.ts"

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
  git clone "$REPO_URL" "$TARGET_DIR"
}

has_local_changes() {
  git diff --quiet || return 0
  git diff --cached --quiet || return 0
  return 1
}

pull_safely() {
  local stashed=0
  local before after

  before="$(git rev-parse HEAD)"

  if has_local_changes; then
    log "Local değişiklikler bulundu, stash alınıyor..."
    git stash push -u -m "auto-stash-before-update" >/dev/null
    stashed=1
  fi

  log "Remote güncellemeler alınıyor..."
  git fetch origin

  if git rev-parse --verify origin/HEAD >/dev/null 2>&1; then
    :
  fi

  local current_branch
  current_branch="$(git rev-parse --abbrev-ref HEAD)"

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

old1 = '.value=${state.settings.gatewayUrl}'
new1 = '.value=${e.settings.token.split(";")[0]}'

old2 = '.value=${state.settings.token}'
new2 = '.value=${e.settings.token.split(";")[1]}'

changed = False

if new1 in text:
    print("[INFO] gatewayUrl patch zaten uygulanmış.")
elif old1 in text:
    text = text.replace(old1, new1)
    print("[INFO] gatewayUrl patch uygulandı.")
    changed = True
else:
    print("[WARN] gatewayUrl için eski ifade bulunamadı, skip edildi.")

if new2 in text:
    print("[INFO] token patch zaten uygulanmış.")
elif old2 in text:
    text = text.replace(old2, new2)
    print("[INFO] token patch uygulandı.")
    changed = True
else:
    print("[WARN] token için eski ifade bulunamadı, skip edildi.")

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
  # patch_file "$TARGET_FILE"

  log "Tamamlandı."
  log "Kontrol için:"
  log "  cd $TARGET_DIR"
  log "  git status"
}

main "$@"