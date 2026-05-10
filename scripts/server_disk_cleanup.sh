#!/usr/bin/env bash
set -euo pipefail

THRESHOLD_PERCENT="${DISK_CLEANUP_THRESHOLD_PERCENT:-80}"
TARGET_PATH="${DISK_CLEANUP_TARGET_PATH:-/}"
APP_DIR="${OPAIRE_APP_DIR:-/home/ubuntu/opaiRe}"
KEEP_LOG_LINES="${DISK_CLEANUP_KEEP_LOG_LINES:-2000}"
MAX_LOG_BYTES="${DISK_CLEANUP_MAX_LOG_BYTES:-5242880}"
DELETE_AFTER_DAYS="${DISK_CLEANUP_DELETE_AFTER_DAYS:-7}"

log() {
  printf '[disk-cleanup] %s\n' "$*"
}

disk_usage_percent() {
  df -P "$TARGET_PATH" | awk 'NR==2 { gsub("%", "", $5); print $5 }'
}

trim_large_log() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    return 0
  fi

  local size
  size=$(stat -c %s "$file" 2>/dev/null || echo 0)
  if (( size <= MAX_LOG_BYTES )); then
    return 0
  fi

  local tmp
  tmp=$(mktemp)
  tail -n "$KEEP_LOG_LINES" "$file" > "$tmp" || true
  cat "$tmp" > "$file"
  rm -f "$tmp"
  log "trimmed log: $file"
}

delete_old_logs() {
  local dir="$1"
  if [[ ! -d "$dir" ]]; then
    return 0
  fi

  find "$dir" -maxdepth 1 -type f \
    \( -name '*.log.*' -o -name '*.out.*' -o -name '*.err.*' -o -name '*.tmp' -o -name '*.cache' \) \
    -mtime +"$DELETE_AFTER_DAYS" -print -delete 2>/dev/null || true
}

cleanup_python_caches() {
  if [[ ! -d "$APP_DIR" ]]; then
    return 0
  fi

  find "$APP_DIR" -type d -name '__pycache__' -prune -print -exec rm -rf {} + 2>/dev/null || true
  find "$APP_DIR" -type f -name '*.pyc' -delete 2>/dev/null || true
}

cleanup_tmp_files() {
  find /tmp -xdev -type f -mtime +"$DELETE_AFTER_DAYS" -print -delete 2>/dev/null || true
  find /var/tmp -xdev -type f -mtime +"$DELETE_AFTER_DAYS" -print -delete 2>/dev/null || true
}

main() {
  local before after
  before=$(disk_usage_percent)
  log "disk usage on $TARGET_PATH before cleanup: ${before}%"

  if (( before < THRESHOLD_PERCENT )); then
    log "below threshold ${THRESHOLD_PERCENT}%, skip cleanup"
    exit 0
  fi

  trim_large_log "$APP_DIR/run.out.log"
  trim_large_log "$APP_DIR/run.err.log"
  trim_large_log "$APP_DIR/data/server.log"
  trim_large_log "$APP_DIR/data/mihomo-pool/mihomo-core.log"

  delete_old_logs "$APP_DIR"
  delete_old_logs "$APP_DIR/data"
  cleanup_python_caches
  cleanup_tmp_files

  journalctl --vacuum-time=7d >/dev/null 2>&1 || true
  apt-get clean >/dev/null 2>&1 || true

  after=$(disk_usage_percent)
  log "disk usage on $TARGET_PATH after cleanup: ${after}%"
}

main "$@"
