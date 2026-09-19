#!/usr/bin/env bash
# build-run.sh VERSION DEB_REVISION ARCH path/to/sonusgrid.deb out/SonusGrid-VER-ARCH.run
set -euo pipefail
VERSION="$1"; REV="$2"; ARCH="$3"; DEB="$4"; OUT="$5"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
[ -f "$DEB" ] || { echo "deb not found: $DEB" >&2; exit 1; }
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
cp "$DEB" "$STAGE/"
cp "$HERE/setup.sh" "$HERE/root-steps.sh" "$STAGE/"
chmod 755 "$STAGE"/*.sh
cp "$ROOT/COPYING" "$STAGE/LICENSE"
cp "$ROOT/docs/en/INSTALL.md" "$STAGE/INSTALL.md"
printf 'VERSION=%s\nDEB_REVISION=%s\nARCH=%s\nDEB=%s\n' "$VERSION" "$REV" "$ARCH" "$(basename "$DEB")" > "$STAGE/manifest"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
# --keep-umask: don't chmod payload; --sha256: embed checksum for `--check`.
sh "$HERE/makeself.sh" --gzip --sha256 --nooverwrite --keep-umask --tar-quietly \
    --header "$HERE/makeself-header.sh" \
    "$STAGE" "$OUT" "SonusGrid $VERSION ($ARCH) installer" ./setup.sh
chmod 755 "$OUT"
"$OUT" --check >/dev/null && echo "Built: $OUT ($(du -h "$OUT" | cut -f1))"
