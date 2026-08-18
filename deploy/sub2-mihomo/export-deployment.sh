#!/usr/bin/env bash
# Build a reusable source bundle from an explicit allowlist. Runtime state and
# credentials cannot enter the archive even when they exist beside this script.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$SOURCE_DIR")"
PACKAGE_DIR="$(basename "$SOURCE_DIR")"
OUTPUT="${1:-${PARENT_DIR}/sub2-mihomo-deploy-$(date +%Y%m%d-%H%M%S).tar.gz}"

if [ -e "$OUTPUT" ]; then
  echo "output already exists: $OUTPUT" >&2
  exit 1
fi

files=(
  README.md
  config.example.yaml
  install.sh
  install-panel.sh
  update-from-github.sh
  export-deployment.sh
  manager.py
  v2ray_convert.py
  mihomoctl
  apply-sticky.sh
  set_subscription.py
  set-subscription.sh
  wire-sub2api-proxy.sh
  sub2-mihomo.service
  sub2-mihomo-panel.service
  sudoers-mihomo
  nginx-mihomo.conf
  web/index.html
  web/app.js
  web/app.css
)

archive_paths=()
for file in "${files[@]}"; do
  if [ ! -f "$SOURCE_DIR/$file" ]; then
    echo "missing deployment file: $file" >&2
    exit 1
  fi
  archive_paths+=("$PACKAGE_DIR/$file")
done
if [ -f "$SOURCE_DIR/REVISION" ]; then
  archive_paths+=("$PACKAGE_DIR/REVISION")
fi

tar -czf "$OUTPUT" -C "$PARENT_DIR" "${archive_paths[@]}"
echo "$OUTPUT"
