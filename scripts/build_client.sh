#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT/client"
# The checked-in rsrc_windows_amd64.syso embeds group icon ID 1.
# Regeneration: assets/make_icons.py documents the offline rsrc command.
mkdir -p dist
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 GOPROXY=off GOSUMDB=off \
  go build -trimpath -ldflags "-s -w -H windowsgui" -o dist/qeukao-client-template.exe .
printf 'Built: %s\n' "$ROOT/client/dist/qeukao-client-template.exe"
