#!/usr/bin/env bash
# Compile static/css/app.css from static/css/src/input.css + tailwind.config.js.
# Run after ANY template or static/js class change, then commit app.css.
# The Tailwind standalone CLI binary is downloaded on first run (gitignored);
# no node/npm required anywhere, and EB deploys are unchanged.
set -euo pipefail
cd "$(dirname "$0")/.."

TAILWIND_VERSION="v3.4.17"
BIN="bin/tailwindcss"

if [ ! -x "$BIN" ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)  ASSET="tailwindcss-macos-arm64" ;;
    Darwin-x86_64) ASSET="tailwindcss-macos-x64" ;;
    Linux-x86_64)  ASSET="tailwindcss-linux-x64" ;;
    Linux-aarch64) ASSET="tailwindcss-linux-arm64" ;;
    *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
  esac
  mkdir -p bin
  echo "Downloading Tailwind CLI ${TAILWIND_VERSION} (${ASSET})..."
  curl -sL -o "$BIN" "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${ASSET}"
  chmod +x "$BIN"
fi

"$BIN" -i static/css/src/input.css -o static/css/app.css --minify "$@"
echo "Built static/css/app.css ($(wc -c < static/css/app.css | tr -d ' ') bytes) — remember to commit it."
