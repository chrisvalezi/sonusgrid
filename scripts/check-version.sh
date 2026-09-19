#!/usr/bin/env bash
# check-version.sh [vX.Y.Z[-rcN]] — verify every version string matches version.mk
# (and the git tag, when given). Used by `make check-version` and CI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
V="$(sed -n 's/^SONUS_VERSION *:= *//p' version.mk)"
REV="$(sed -n 's/^DEB_REVISION *:= *//p' version.mk)"
TAG="${1:-}"
fail=0
chk() { if eval "$2"; then echo "  ✓ $1"; else echo "  ✗ $1"; fail=1; fi; }
echo "version.mk: $V-$REV"
if [ -n "$TAG" ]; then
    chk "tag $TAG matches v$V" "[ \"${TAG%%-*}\" = \"v$V\" ]"
fi
chk "crates/sonus-cli/Cargo.toml"        "grep -q '^version = \"$V\"' crates/sonus-cli/Cargo.toml"
chk "crates/sonusgrid-bridge/Cargo.toml" "grep -q '^version = \"$V\"' crates/sonusgrid-bridge/Cargo.toml"
chk "packaging/debian/changelog"         "head -1 packaging/debian/changelog | grep -q '^sonusgrid ($V-$REV)'"
chk "CHANGELOG.md has ## [$V]"           "grep -q '^## \[$V\]' CHANGELOG.md"
chk "metainfo has release $V"            "grep -q 'release version=\"$V\"' gui/sonus-gtk/data/io.sonusgrid.SonusGrid.metainfo.xml"
exit $fail
