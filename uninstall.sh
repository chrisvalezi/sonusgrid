#!/usr/bin/env bash
# Remove SonusGrid. Keeps ~/.config/sonusgrid unless --purge is given.
set -euo pipefail
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
[ "$(id -u)" -ne 0 ] || { echo "run as your normal user (the script calls sudo)"; exit 1; }

# Stop + disable the user services first.
systemctl --user stop sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true
systemctl --user disable sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true
systemctl --user reset-failed sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true

if dpkg -s sonusgrid >/dev/null 2>&1; then
    if [ "$PURGE" -eq 1 ]; then sudo apt-get purge -y sonusgrid; else sudo apt-get remove -y sonusgrid; fi
else
    ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    sudo make -C "$ROOT" uninstall PREFIX=/usr
    sudo rm -f /etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf
    sudo ldconfig
fi

# Per-user leftovers.
rm -rf "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/sonusgrid" 2>/dev/null || true
rm -rf "$HOME/.cache/sonusgrid"
rm -f "$HOME/.config/alsa/sonusgrid.conf"
if [ -f "$HOME/.asoundrc" ]; then
    sed -i '/^# >>> sonusgrid/,/^# <<< sonusgrid/d' "$HOME/.asoundrc"
fi
if [ "$PURGE" -eq 1 ]; then
    rm -rf "$HOME/.config/sonusgrid"
    echo "SonusGrid removed, including ~/.config/sonusgrid."
else
    echo "SonusGrid removed. Config kept at ~/.config/sonusgrid (use --purge to delete)."
fi
