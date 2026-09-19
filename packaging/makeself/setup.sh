#!/usr/bin/env bash
# =============================================================================
#  SonusGrid .run installer — payload entry point.
#  Runs as the invoking (regular) user; elevates exactly once for the
#  privileged steps in root-steps.sh.
#
#  Options (after `--` on the .run command line):
#    --yes         no questions
#    --no-launch   don't offer to open the GUI
#    --deb-only    don't pull pipewire-jack/pavucontrol/wireplumber extras
#    --uninstall   remove SonusGrid (keeps ~/.config/sonusgrid)
#    --purge       with --uninstall: also remove the config
#    --help
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
# shellcheck disable=SC1091
. ./manifest

YES=0; LAUNCH=1; DEB_ONLY=0; UNINSTALL=0; PURGE=0
for a in "$@"; do
    case "$a" in
        --yes|-y) YES=1 ;;
        --no-launch) LAUNCH=0 ;;
        --deb-only) DEB_ONLY=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --purge) PURGE=1 ;;
        --) ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
        *) echo "unknown option: $a (try --help)" >&2; exit 2 ;;
    esac
done

# ---- terminal plumbing --------------------------------------------------------
if [ ! -t 0 ] && [ -r /dev/tty ]; then exec </dev/tty; fi   # piped (curl | bash): read prompts from the tty
if [ ! -t 1 ]; then
    # makeself could not find a terminal emulator (no DISPLAY?) — tell the user how to run us.
    msg="SonusGrid: abra um terminal e rode o instalador / open a terminal and run the installer."
    zenity --error --text "$msg" 2>/dev/null || notify-send "SonusGrid" "$msg" 2>/dev/null || true
    echo "$msg" >&2
    exit 2
fi
if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B=""; G=""; Y=""; R=""; N=""; fi
say()  { printf '%s\n' "${B}==>${N} $*"; }
ok()   { printf '%s\n' "  ${G}✓${N} $*"; }
warn() { printf '%s\n' "  ${Y}!${N} $*"; }
die()  { printf '%s\n' "${R}erro/error:${N} $*" >&2; exit 1; }
# (When double-clicked, makeself re-opens us in a terminal with --xwin and
#  itself waits for Enter before closing the window.)
ask() {  # ask "question" -> 0 yes / 1 no ; default yes
    [ "$YES" -eq 1 ] && return 0
    printf '%s [S/n] ' "$1"; read -r ans || ans=""
    case "${ans:-s}" in [SsYy]*) return 0 ;; *) return 1 ;; esac
}
elevate() {
    if command -v sudo >/dev/null 2>&1; then
        if sudo -n true 2>/dev/null || sudo -v; then sudo "$@"; return; fi
    fi
    if command -v pkexec >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        pkexec "$@"; return
    fi
    echo "Senha do root / root password:"
    su -c "$(printf '%q ' "$@")"
}

# ---- guards ---------------------------------------------------------------------
say "SonusGrid ${VERSION} (${ARCH})"
eval "$(grep -E '^(ID|ID_LIKE)=' /etc/os-release 2>/dev/null)" || true   # only ID/ID_LIKE — os-release also defines VERSION
case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*|*" elementary "*|*" zorin "*|*" kali "*|*" raspbian "*) ;;
    *) die "Este instalador é para Debian/Ubuntu/Mint. Para Fedora/Arch/openSUSE compile do fonte (INSTALL.md).
       This installer is for Debian/Ubuntu/Mint. For Fedora/Arch/openSUSE build from source (INSTALL.md)." ;;
esac
command -v apt-get >/dev/null || die "apt-get não encontrado / not found"
HOST_ARCH="$(dpkg --print-architecture)"
[ "$HOST_ARCH" = "$ARCH" ] || die "este instalador é ${ARCH}, seu sistema é ${HOST_ARCH} — baixe SonusGrid-${VERSION}-${HOST_ARCH}.run
       this installer is ${ARCH}, your system is ${HOST_ARCH} — download SonusGrid-${VERSION}-${HOST_ARCH}.run"
ME="$(id -un)"
if [ "$(id -u)" -eq 0 ]; then
    ME="${SUDO_USER:-}"
    warn "rodando como root; os passos por usuário serão feitos para '${ME:-<ninguém>}' / running as root; per-user steps for '${ME:-<nobody>}'"
fi

# ---- uninstall -----------------------------------------------------------------------
if [ "$UNINSTALL" -eq 1 ]; then
    ask "Remover o SonusGrid? / Remove SonusGrid?" || exit 0
    systemctl --user stop sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true
    systemctl --user disable sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true
    systemctl --user reset-failed sonusgrid-audio.service sonusgrid-clock.service 2>/dev/null || true
    elevate "$HERE/root-steps.sh" uninstall $([ "$PURGE" -eq 1 ] && echo --purge)
    rm -rf "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/sonusgrid" "$HOME/.cache/sonusgrid" 2>/dev/null || true
    rm -f "$HOME/.config/alsa/sonusgrid.conf"
    [ -f "$HOME/.asoundrc" ] && sed -i '/^# >>> sonusgrid/,/^# <<< sonusgrid/d' "$HOME/.asoundrc"
    [ "$PURGE" -eq 1 ] && rm -rf "$HOME/.config/sonusgrid"
    ok "SonusGrid removido / removed"
    exit 0
fi

# ---- install ----------------------------------------------------------------------------
INSTALLED="$(dpkg-query -W -f='${Version}' sonusgrid 2>/dev/null || true)"
if [ -n "$INSTALLED" ]; then
    say "Versão instalada: ${INSTALLED} → ${VERSION}-${DEB_REVISION} / installed version ${INSTALLED} → ${VERSION}-${DEB_REVISION}"
fi
EXTRAS="pipewire-jack wireplumber pavucontrol"
[ "$DEB_ONLY" -eq 1 ] && EXTRAS=""
cat <<EOT

  O instalador vai / The installer will:
    • instalar o pacote sonusgrid ${VERSION} via apt (dependências incluídas)
      install the sonusgrid ${VERSION} package via apt (with dependencies)
$( [ -n "$EXTRAS" ] && printf '    • instalar / install: %s\n' "$EXTRAS" )
    • adicionar '${ME}' ao grupo 'audio' (relógio PTP de hardware)
      add '${ME}' to the 'audio' group (hardware PTP clock)
  Será pedida sua senha (sudo). / Your password (sudo) will be requested.

EOT
ask "Continuar? / Continue?" || exit 0

MARK="$(mktemp)"
elevate "$HERE/root-steps.sh" install "$HERE/$DEB" "$ME" "$MARK" $EXTRAS
GROUP_ADDED=0; grep -q GROUP_ADDED "$MARK" 2>/dev/null && GROUP_ADDED=1; rm -f "$MARK"
hash -r
ok "pacote instalado / package installed: $(sonusgrid version 2>/dev/null | head -1)"

# ---- per-user ----------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    [ -f "$HOME/.config/sonusgrid/config.toml" ] || { sonusgrid config init >/dev/null 2>&1 && ok "config criado / created: ~/.config/sonusgrid/config.toml"; }
    echo; sonusgrid doctor || true; echo
fi
if [ "$GROUP_ADDED" -eq 1 ]; then
    warn "Você entrou no grupo 'audio': faça logout/login antes de iniciar (relógio PTP de hardware)."
    warn "You were added to the 'audio' group: log out and back in before starting (hardware PTP clock)."
fi

cat <<EOT
${B}SonusGrid ${VERSION} instalado / installed.${N}

  1. Escolha a placa de rede ligada ao switch Dante / Pick the NIC on the Dante switch:
       GUI: SonusGrid → Configuração → Interface de rede → Aplicar
       CLI: sonusgrid config edit
  2. Inicie / Start:   sonusgrid start      (ou o botão Iniciar na GUI / or the Start button)
  3. Roteie no Dante Controller / Route in Dante Controller (Windows/macOS PC, same LAN).

  Diagnóstico / diagnostics:  sonusgrid doctor       Logs:  sonusgrid logs -f
  Desinstalar / uninstall:    ./SonusGrid-${VERSION}-${ARCH}.run -- --uninstall
EOT

if [ "$LAUNCH" -eq 1 ] && [ "$(id -u)" -ne 0 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    if ask "Abrir o SonusGrid agora? / Open SonusGrid now?"; then
        if command -v setsid >/dev/null; then setsid -f sonusgrid-gtk >/dev/null 2>&1 </dev/null
        else nohup sonusgrid-gtk >/dev/null 2>&1 </dev/null & fi
        ok "GUI aberta / GUI launched"
    fi
fi
