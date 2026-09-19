#!/usr/bin/env bash
# Privileged part of the SonusGrid .run installer. Idempotent, no prompts.
#   root-steps.sh install DEB USER MARKFILE [extra packages…]
#   root-steps.sh uninstall [--purge]
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
cmd="${1:-}"; shift || true
case "$cmd" in
    install)
        DEB="$1"; USER_NAME="$2"; MARK="$3"; shift 3
        [ -f "$DEB" ] || { echo "deb not found: $DEB" >&2; exit 1; }
        # apt's sandboxed _apt user must be able to read the file.
        TMP="$(mktemp -d)"; chmod 755 "$TMP"; cp "$DEB" "$TMP/"; chmod 644 "$TMP"/*.deb
        apt-get update -qq || true
        apt-get install -y -qq "$TMP/$(basename "$DEB")" "$@"
        rm -rf "$TMP"
        if [ -n "$USER_NAME" ] && getent group audio >/dev/null && ! id -nG "$USER_NAME" 2>/dev/null | grep -qw audio; then
            usermod -aG audio "$USER_NAME" && echo GROUP_ADDED >> "$MARK"
        fi
        ;;
    uninstall)
        if [ "${1:-}" = "--purge" ]; then apt-get purge -y -qq sonusgrid; else apt-get remove -y -qq sonusgrid; fi
        ;;
    *) echo "usage: root-steps.sh install DEB USER MARK [pkgs…] | uninstall [--purge]" >&2; exit 2 ;;
esac
