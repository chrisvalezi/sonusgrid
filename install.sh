#!/usr/bin/env bash
# =============================================================================
#  SonusGrid installer
#
#  Usage:
#    ./install.sh                 # install: uses dist/*.deb if present, else builds
#    ./install.sh --build         # force a build from source
#    ./install.sh --deb FILE.deb  # install a specific .deb
#    ./install.sh --no-start      # don't offer to start after installing
#    ./install.sh --help
#
#  Run as your normal user (NOT with sudo). The script calls sudo itself only
#  for the steps that need root.
#
#  Debian / Ubuntu / Mint  -> builds/installs the .deb (postinst does the
#                             system-level setup: capabilities, udev, ld.so)
#  Fedora / Arch / other   -> builds from source, `make install`, then
#                             performs the same system-level setup here.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

FORCE_BUILD=0
DEB_FILE=""
NO_START=0

# ---- colours ---------------------------------------------------------------
if [ -t 1 ]; then
    B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'
else
    B=""; G=""; Y=""; R=""; N=""
fi
say()  { printf '%s\n' "${B}==>${N} $*"; }
ok()   { printf '%s\n' "  ${G}✓${N} $*"; }
warn() { printf '%s\n' "  ${Y}!${N} $*"; }
die()  { printf '%s\n' "${R}error:${N} $*" >&2; exit 1; }

usage() { sed -n '2,20p' "$0" | sed 's/^#  \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --build)     FORCE_BUILD=1 ;;
        --deb)       shift; DEB_FILE="${1:-}"; [ -n "$DEB_FILE" ] || die "--deb needs a file" ;;
        --no-start)  NO_START=1 ;;
        -h|--help)   usage ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not as root/sudo (the script calls sudo when needed)"
command -v sudo >/dev/null || die "sudo is required"

# ---- detect distro ---------------------------------------------------------
. /etc/os-release 2>/dev/null || true
DISTRO_ID="${ID:-unknown}"
DISTRO_LIKE="${ID_LIKE:-}"
ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in
    x86_64) ARCH=amd64 ;;
    aarch64) ARCH=arm64 ;;
esac

is_deb_family() {
    case " $DISTRO_ID $DISTRO_LIKE " in
        *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*|*" elementary "*|*" zorin "*|*" kali "*) return 0 ;;
    esac
    return 1
}

say "SonusGrid installer — ${DISTRO_ID} (${ARCH})"

# ---- helpers ---------------------------------------------------------------
VERSION="$(sed -n 's/^SONUS_VERSION *:= *//p' version.mk)"
DEB_REVISION="$(sed -n 's/^DEB_REVISION *:= *//p' version.mk)"
DEB_REVISION="${DEB_REVISION:-1}"

ensure_rust() {
    if command -v cargo >/dev/null; then
        ok "cargo: $(cargo --version)"
        return
    fi
    if [ -x "$HOME/.cargo/bin/cargo" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
        ok "cargo: $(cargo --version) (from ~/.cargo/bin)"
        return
    fi
    warn "Rust toolchain not found."
    printf '    Install it now with rustup (https://rustup.rs)? [Y/n] '
    read -r ans
    case "${ans:-Y}" in
        [Yy]*) curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
               export PATH="$HOME/.cargo/bin:$PATH"
               ok "cargo: $(cargo --version)" ;;
        *) die "Rust is required to build from source" ;;
    esac
}

apt_install() {
    say "Installing packages with apt: $*"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
}

install_build_deps_deb() {
    apt_install build-essential pkg-config devscripts debhelper dpkg-dev \
        libasound2-dev libpulse-dev libjack-jackd2-dev python3 \
        pipewire pipewire-pulse pipewire-jack wireplumber pulseaudio-utils alsa-utils \
        python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libcap2-bin pavucontrol qpwgraph
}

install_deps_other() {
    case "$DISTRO_ID" in
        fedora|rhel|centos|rocky|almalinux)
            say "Installing packages with dnf"
            sudo dnf install -y gcc make pkgconf-pkg-config alsa-lib-devel pulseaudio-libs-devel \
                jack-audio-connection-kit-devel python3 python3-gobject gtk4 libadwaita \
                pipewire pipewire-pulseaudio pipewire-jack-audio-connection-kit pulseaudio-utils \
                alsa-utils libcap ;;
        arch|manjaro|endeavouros)
            say "Installing packages with pacman"
            sudo pacman -S --needed --noconfirm base-devel pkgconf alsa-lib libpulse jack2 python \
                python-gobject gtk4 libadwaita pipewire pipewire-pulse pipewire-jack libpulse alsa-utils libcap ;;
        opensuse*|sles)
            say "Installing packages with zypper"
            sudo zypper install -y gcc make pkg-config alsa-devel libpulse-devel libjack-devel python3 \
                python3-gobject gtk4 libadwaita pipewire pipewire-pulseaudio pipewire-jack alsa-utils libcap-progs ;;
        *)
            warn "Unknown distro '$DISTRO_ID' — make sure you have: gcc, pkg-config, ALSA/libpulse/JACK dev headers,"
            warn "python3-gobject >= 3.46, GTK4 >= 4.12, libadwaita >= 1.5, PipeWire (+pulse +jack +wireplumber), pactl, setcap." ;;
    esac
}

# System-level setup that the .deb postinst normally does. Used on
# non-Debian distros after `make install`.
system_setup_manual() {
    say "System setup (capabilities, ld.so, udev)"
    sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep /usr/libexec/sonusgrid/statime \
        && ok "statime capabilities" || warn "setcap failed — PTP clock will not work"
    local d
    for d in /usr/lib/x86_64-linux-gnu/pipewire-0.3/jack /usr/lib/aarch64-linux-gnu/pipewire-0.3/jack \
             /usr/lib64/pipewire-0.3/jack /usr/lib/pipewire-0.3/jack; do
        if [ -e "$d/libjack.so.0" ]; then
            echo "$d" | sudo tee /etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf >/dev/null
            sudo ldconfig
            ok "libjack → PipeWire-JACK ($d)"
            break
        fi
    done
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger /dev/ptp* 2>/dev/null || true
    sudo gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
    sudo update-desktop-database -q 2>/dev/null || true
}

post_install_user() {
    say "Post-install checks"
    if getent group audio >/dev/null && ! id -nG "$USER" | grep -qw audio; then
        warn "Your user is not in the 'audio' group (needed for /dev/ptp* hardware clocks)."
        printf '    Add %s to the audio group now? [Y/n] ' "$USER"
        read -r ans
        case "${ans:-Y}" in
            [Yy]*) sudo usermod -aG audio "$USER"; ok "added — log out and back in for it to take effect" ;;
        esac
    else
        ok "user is in the audio group"
    fi

    if [ ! -f "$HOME/.config/sonusgrid/config.toml" ]; then
        sonusgrid config init >/dev/null 2>&1 || true
        ok "created ~/.config/sonusgrid/config.toml"
    fi

    echo
    sonusgrid doctor || true
    echo

    cat <<EOT
${B}SonusGrid ${VERSION} installed.${N}

  1. Pick the network interface connected to the Dante switch:
       GUI:  menu → SonusGrid → Configuração → Interface de rede → Aplicar
       CLI:  sonusgrid config edit     (set [network].interface = "enpXsY")
  2. Start it:   sonusgrid start        (or the GUI's Start button)
  3. Route channels with Dante Controller on a Windows/Mac PC in the same LAN.

  Diagnostics:  sonusgrid doctor   ·   Logs:  sonusgrid logs -f
EOT

    if [ "$NO_START" -eq 0 ]; then
        local iface
        iface="$(sed -n 's/^interface *= *"\(.*\)"/\1/p' "$HOME/.config/sonusgrid/config.toml" 2>/dev/null | head -1)"
        if [ -n "$iface" ]; then
            printf '\n  Interface "%s" is configured. Start SonusGrid now? [Y/n] ' "$iface"
            read -r ans
            case "${ans:-Y}" in [Yy]*) sonusgrid start || true ;; esac
        fi
    fi
}

# ---- main ------------------------------------------------------------------
if is_deb_family; then
    # Prefer a prebuilt .deb (dist/ or --deb) unless --build was given.
    if [ -z "$DEB_FILE" ] && [ "$FORCE_BUILD" -eq 0 ]; then
        DEB_FILE="$(ls -1 dist/sonusgrid_${VERSION}-*_${ARCH}.deb 2>/dev/null | sort -V | tail -1 || true)"
    fi
    if [ -z "$DEB_FILE" ]; then
        say "No prebuilt package for ${ARCH}; building from source"
        install_build_deps_deb
        ensure_rust
        make deb
        DEB_FILE="dist/sonusgrid_${VERSION}-${DEB_REVISION}_${ARCH}.deb"
    fi
    [ -f "$DEB_FILE" ] || die "package not found: $DEB_FILE"
    say "Installing $DEB_FILE"
    # apt (not dpkg) so runtime dependencies get pulled in.
    sudo apt-get update -qq || true
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "./$DEB_FILE"
    ok "package installed"
else
    say "Non-Debian distro: building from source and installing to /usr"
    install_deps_other
    ensure_rust
    make build
    sudo make install PREFIX=/usr
    ok "installed to /usr"
    system_setup_manual
fi

hash -r
command -v sonusgrid >/dev/null || die "sonusgrid is not on PATH after install"
post_install_user
