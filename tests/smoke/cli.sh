#!/usr/bin/env bash
# Smoke test for the sonusgrid CLI. Runs against the freshly built binary
# (or the installed one) without touching systemd or the audio stack.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/../.." && pwd)
BIN=${SONUSGRID_BIN:-$HERE/crates/sonus-cli/target/release/sonusgrid}
[ -x "$BIN" ] || BIN=$(command -v sonusgrid || true)
[ -x "$BIN" ] || { echo "sonusgrid binary not found (build first: make build-cli)"; exit 1; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
CFG=$TMP/config.toml

echo "== version";      "$BIN" version | head -1
echo "== help";         "$BIN" --help >/dev/null
echo "== config init";  "$BIN" --config "$CFG" config init >/dev/null
[ -f "$CFG" ] || { echo "config init did not create $CFG"; exit 1; }
echo "== config show";  "$BIN" --config "$CFG" config show | grep -q '^\[device\]'
echo "== config check must fail with empty interface"
if "$BIN" --config "$CFG" config check --quiet 2>/dev/null; then
  echo "expected config check to fail on empty network.interface"; exit 1
fi
echo "== config check passes with an interface"
sed -i 's/^interface = ""/interface = "lo"/' "$CFG"
"$BIN" --config "$CFG" config check --quiet
echo "== status --json is valid JSON"
"$BIN" --config "$CFG" status --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["mode"]=="unified"; assert "clock_state" in d'
echo "== start must refuse a nonexistent interface"
sed -i 's/^interface = "lo"/interface = "does-not-exist0"/' "$CFG"
if "$BIN" --config "$CFG" start >/dev/null 2>&1; then
  echo "expected start to refuse a nonexistent interface"; exit 1
fi
echo "smoke OK"
