#!/usr/bin/env bash
# bump-version.sh X.Y.Z — set the version everywhere and open a changelog stanza.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
NEW="${1:?usage: bump-version.sh X.Y.Z}"
echo "$NEW" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "bad version: $NEW"; exit 1; }
OLD="$(sed -n 's/^SONUS_VERSION *:= *//p' version.mk)"
DATE_ISO="$(date +%F)"; DATE_RFC="$(date -R)"
AUTHOR="Chris Valezi <chrisvalezi@gmail.com>"

sed -i "s/^SONUS_VERSION *:=.*/SONUS_VERSION := $NEW/; s/^DEB_REVISION *:=.*/DEB_REVISION  := 1/" version.mk
for f in crates/sonus-cli/Cargo.toml crates/sonusgrid-bridge/Cargo.toml; do
    sed -i "0,/^version = \".*\"/s//version = \"$NEW\"/" "$f"
    (cd "$(dirname "$f")" && cargo update -q --offline -p "$(sed -n 's/^name = "\(.*\)"/\1/p' Cargo.toml | head -1)" 2>/dev/null || true)
done
# debian/changelog stanza
{
    printf 'sonusgrid (%s-1) unstable; urgency=medium\n\n  * Release %s. See CHANGELOG.md.\n\n -- %s  %s\n\n' "$NEW" "$NEW" "$AUTHOR" "$DATE_RFC"
    cat packaging/debian/changelog
} > packaging/debian/changelog.new && mv packaging/debian/changelog.new packaging/debian/changelog
# CHANGELOG.md: rename [Unreleased] or insert a header (unless the section already exists)
if grep -q "^## \[$NEW\]" CHANGELOG.md; then
    :
elif grep -q '^## \[Unreleased\]' CHANGELOG.md; then
    sed -i "s/^## \[Unreleased\].*/## [Unreleased]\n\n## [$NEW] — $DATE_ISO/" CHANGELOG.md
else
    sed -i "0,/^## \[/s//## [$NEW] — $DATE_ISO\n\n(describe the changes)\n\n## [/" CHANGELOG.md
    echo "note: added an empty '## [$NEW]' section to CHANGELOG.md — fill it in"
fi
# metainfo release entry
grep -q "release version=\"$NEW\"" gui/sonus-gtk/data/io.sonusgrid.SonusGrid.metainfo.xml || sed -i "s|  <releases>|  <releases>\n    <release version=\"$NEW\" date=\"$DATE_ISO\"><description><p>Release $NEW.</p></description></release>|" gui/sonus-gtk/data/io.sonusgrid.SonusGrid.metainfo.xml
echo "bumped $OLD → $NEW"
bash scripts/check-version.sh
cat <<EOT

next:
  git add -A && git commit -m "Release $NEW"
  git tag -a v$NEW -m "SonusGrid $NEW"
  git push --follow-tags          # CI builds the release
EOT
