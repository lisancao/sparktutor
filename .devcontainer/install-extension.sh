#!/usr/bin/env bash
# Install the SparkTutor VSIX into the VS Code remote extensions directory.
# Works in Codespaces where `code` CLI is not available during postCreateCommand.
set -euo pipefail

VSIX=$(ls sparktutor-vscode/sparktutor-*.vsix 2>/dev/null | head -1)
if [ -z "$VSIX" ]; then
  echo "ERROR: No .vsix file found. Did onCreateCommand succeed?"
  exit 1
fi

VERSION=$(echo "$VSIX" | sed 's/.*sparktutor-\(.*\)\.vsix/\1/')
EXT_DIR="$HOME/.vscode-remote/extensions/sparktutor.sparktutor-${VERSION}"

echo "Installing SparkTutor v${VERSION} to ${EXT_DIR}..."

rm -rf "$EXT_DIR"
mkdir -p "$EXT_DIR"

# VSIX is a zip with extension/ prefix — extract and flatten
TMP=$(mktemp -d)
unzip -q "$VSIX" 'extension/*' -d "$TMP"
cp -r "$TMP/extension/"* "$EXT_DIR/"
rm -rf "$TMP"

echo "SparkTutor extension installed successfully."
