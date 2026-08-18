#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${MIHOMO_GITHUB_REPOSITORY:-YuHaiA/opaiRe}"
RELEASE_TAG="${MIHOMO_RELEASE_TAG:-mihomo-deploy}"
PACKAGE_NAME="sub2-mihomo-deploy.tar.gz"
RELEASE_BASE="https://github.com/${REPOSITORY}/releases/download/${RELEASE_TAG}"
PACKAGE_URL="${MIHOMO_PACKAGE_URL:-${RELEASE_BASE}/${PACKAGE_NAME}}"
CHECKSUM_URL="${MIHOMO_CHECKSUM_URL:-${PACKAGE_URL}.sha256}"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

for command in curl sha256sum tar; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing command: $command" >&2; exit 1; }
done

curl -fsSL --retry 3 --retry-delay 2 "$PACKAGE_URL" -o "$WORK_DIR/$PACKAGE_NAME"
curl -fsSL --retry 3 --retry-delay 2 "$CHECKSUM_URL" -o "$WORK_DIR/$PACKAGE_NAME.sha256"
(
  cd "$WORK_DIR"
  sha256sum -c "$PACKAGE_NAME.sha256"
)

while IFS= read -r path; do
  case "$path" in
    sub2-mihomo/*) ;;
    *) echo "unexpected archive path: $path" >&2; exit 1 ;;
  esac
  case "/$path/" in
    */../*) echo "unsafe archive path: $path" >&2; exit 1 ;;
  esac
done < <(tar -tzf "$WORK_DIR/$PACKAGE_NAME")

tar -xzf "$WORK_DIR/$PACKAGE_NAME" -C "$WORK_DIR"
if [ "${MIHOMO_VERIFY_ONLY:-0}" = "1" ]; then
  echo "MIHOMO_PACKAGE_VERIFY_OK repository=$REPOSITORY tag=$RELEASE_TAG"
  exit 0
fi
MIHOMO_RESTART_CORE="${MIHOMO_RESTART_CORE:-0}" \
  bash "$WORK_DIR/sub2-mihomo/install-panel.sh"

revision="$(cat "$WORK_DIR/sub2-mihomo/REVISION" 2>/dev/null || true)"
echo "MIHOMO_GITHUB_UPDATE_OK repository=$REPOSITORY tag=$RELEASE_TAG revision=${revision:-unknown}"
