#!/usr/bin/env bash
# =============================================================================
#  SonusGrid one-line installer (Debian / Ubuntu / Mint, amd64 + arm64)
#
#    curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
#    wget -qO-  https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
#
#  Options are forwarded to the .run installer:
#    curl … | bash -s -- --yes --no-launch
#    curl … | bash -s -- --uninstall
#
#  Environment:
#    SONUSGRID_VERSION=v0.3.0   install a specific tag instead of the latest release
#    SONUSGRID_BASE_URL=…       override the download base (file:///path/to/dist for local tests)
#
#  Downloads SHA256SUMS + the .run for your architecture, verifies the
#  checksum and runs it. Nothing is installed by this script itself.
# =============================================================================
set -euo pipefail
[ "${1:-}" = "--" ] && shift          # `bash install.sh -- --yes` keeps the "--"; `bash -s -- --yes` does not
REPO="chrisvalezi/sonusgrid"
TAG="${SONUSGRID_VERSION:-latest}"
if [ -n "${SONUSGRID_BASE_URL:-}" ]; then BASE="$SONUSGRID_BASE_URL"
elif [ "$TAG" = "latest" ]; then BASE="https://github.com/$REPO/releases/latest/download"
else BASE="https://github.com/$REPO/releases/download/$TAG"; fi

die() { printf 'SonusGrid installer: %s\n' "$*" >&2; exit 1; }
if [ ! -t 0 ] && [ -r /dev/tty ]; then exec </dev/tty; fi          # we are piped; prompts must read the tty
[ "$(id -u)" -ne 0 ] || die "run as your normal user — the installer asks for sudo itself"
eval "$(grep -E '^(ID|ID_LIKE)=' /etc/os-release 2>/dev/null)" || true   # only ID/ID_LIKE — os-release also defines VERSION
case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*|*" elementary "*|*" zorin "*|*" kali "*|*" raspbian "*) ;;
    *) die "prebuilt packages exist for Debian/Ubuntu/Mint only. Other distros: git clone https://github.com/$REPO && ./install.sh" ;;
esac
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in amd64|arm64) ;; x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; *) die "no prebuilt package for $ARCH" ;; esac

fetch() {  # fetch URL DEST
    if command -v curl >/dev/null; then curl -fsSL --retry 3 -o "$2" "$1"
    elif command -v wget >/dev/null; then wget -q -O "$2" "$1"
    else die "need curl or wget"; fi
}
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "==> SonusGrid $TAG ($ARCH) — fetching from $BASE"
fetch "$BASE/SHA256SUMS" "$TMP/SHA256SUMS" || die "could not download SHA256SUMS from $BASE"
RUN="$(awk -v a="-$ARCH.run" 'index($2, a) && substr($2, length($2)-length(a)+1) == a { print $2; exit }' "$TMP/SHA256SUMS")"
[ -n "$RUN" ] || die "release has no .run installer for $ARCH"
fetch "$BASE/$RUN" "$TMP/$RUN" || die "could not download $RUN"
( cd "$TMP" && grep " $RUN\$" SHA256SUMS | sha256sum -c --quiet - ) || die "checksum mismatch for $RUN"
chmod +x "$TMP/$RUN"
echo "==> checksum OK, running $RUN"
"$TMP/$RUN" -- "$@"
