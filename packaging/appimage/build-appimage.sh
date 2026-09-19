#!/usr/bin/env bash
# build-appimage.sh — assemble Sonus-<arch>.AppImage from already-built
# Cargo artefacts. Run from the project root.
#
# Usage:
#   bash packaging/appimage/build-appimage.sh [VERSION] [ARCH]
#
#   ARCH: x86_64 (default) | aarch64
#
# For aarch64 cross-builds, run `make build TARGET=aarch64-unknown-linux-gnu`
# beforehand so the binaries exist under target/aarch64-unknown-linux-gnu/.

set -euo pipefail

VERSION="${1:-0.1.0}"
ARCH="${2:-x86_64}"
ROOT="$(cd "$(dirname "${0}")/../.." && pwd)"

case "${ARCH}" in
    x86_64)
        TARGET_DIR=""
        APPDIR_LIBDIR="usr/lib/alsa-lib"
        ;;
    aarch64)
        TARGET_DIR="aarch64-unknown-linux-gnu/"
        APPDIR_LIBDIR="usr/lib/alsa-lib"
        ;;
    *)
        echo "ERROR: unknown ARCH '${ARCH}' (supported: x86_64, aarch64)" >&2
        exit 1
        ;;
esac

CLI_BIN="${ROOT}/crates/sonus-cli/target/${TARGET_DIR}release/sonusgrid"
STATIME_BIN="${ROOT}/vendor/statime/target/${TARGET_DIR}release/statime"
INFERNO_LIB="${ROOT}/crates/sonusgrid-engine/target/${TARGET_DIR}release/libasound_module_pcm_sonusgrid.so"
INFERNO2PIPE="${ROOT}/crates/sonusgrid-engine/target/${TARGET_DIR}release/sonusgrid_pipe"

BUILD="${ROOT}/build/appimage-${ARCH}"
APPDIR="${BUILD}/SonusGrid.AppDir"

# 1. Sanity --------------------------------------------------------------
for f in "${CLI_BIN}" "${STATIME_BIN}" "${INFERNO_LIB}" "${INFERNO2PIPE}"; do
    [ -f "${f}" ] || { echo "missing: ${f} (build for ${ARCH} first)"; exit 1; }
done

# 2. Layout --------------------------------------------------------------
rm -rf "${APPDIR}"
mkdir -p \
    "${APPDIR}/usr/bin" \
    "${APPDIR}/usr/libexec/sonusgrid" \
    "${APPDIR}/${APPDIR_LIBDIR}" \
    "${APPDIR}/usr/lib/systemd/user/pipewire.service.d" \
    "${APPDIR}/usr/share/applications" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps" \
    "${APPDIR}/usr/share/sonusgrid/gui"

# 3. Stage binaries / libraries -----------------------------------------
install -m 0755 "${CLI_BIN}"          "${APPDIR}/usr/bin/sonusgrid"
install -m 0755 "${STATIME_BIN}"      "${APPDIR}/usr/libexec/sonusgrid/statime"
install -m 0755 "${INFERNO2PIPE}"     "${APPDIR}/usr/libexec/sonusgrid/sonusgrid_pipe"
install -m 0755 "${INFERNO_LIB}"      "${APPDIR}/${APPDIR_LIBDIR}/libasound_module_pcm_sonusgrid.so"

install -m 0755 "${ROOT}/gui/sonus-gtk/sonusgrid-gtk.sh"  "${APPDIR}/usr/bin/sonusgrid-gtk"

install -m 0644 "${ROOT}/systemd/sonusgrid-clock.service" "${APPDIR}/usr/lib/systemd/user/"
install -m 0644 "${ROOT}/systemd/sonusgrid-audio.service" "${APPDIR}/usr/lib/systemd/user/"
install -m 0644 "${ROOT}/systemd/sonusgrid-pipewire-clock.conf" \
    "${APPDIR}/usr/lib/systemd/user/pipewire.service.d/"

cp -r "${ROOT}/gui/sonus-gtk/sonus_gtk" "${APPDIR}/usr/share/sonusgrid/gui/"

install -m 0644 "${ROOT}/gui/sonus-gtk/data/io.sonusgrid.SonusGrid.desktop" \
    "${APPDIR}/usr/share/applications/"
install -m 0644 "${ROOT}/gui/sonus-gtk/data/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps/"

# Top-level files required by appimagetool.
install -m 0644 "${ROOT}/gui/sonus-gtk/data/io.sonusgrid.SonusGrid.desktop" "${APPDIR}/SonusGrid.desktop"
install -m 0644 "${ROOT}/gui/sonus-gtk/data/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg" \
    "${APPDIR}/io.sonusgrid.SonusGrid.svg"
install -m 0755 "${ROOT}/packaging/appimage/AppRun" "${APPDIR}/AppRun"
sed -i 's|^Exec=.*|Exec=AppRun|' "${APPDIR}/SonusGrid.desktop"

# 4. linuxdeploy + appimagetool -----------------------------------------
# linuxdeploy bundles GTK/python deps (always run on x86_64 host even when
# the target is aarch64 — it understands ELF arch from the binaries it
# inspects via objdump/readelf, but for a foreign target we skip the
# bundling step and rely on the host system's GTK/python being present at
# runtime). For full self-containment on aarch64 hosts we'd need to run
# linuxdeploy under qemu — out of scope here.

LINUXDEPLOY_X86="$(command -v linuxdeploy 2>/dev/null || echo "$HOME/.local/bin/linuxdeploy")"
APPIMAGETOOL_X86="$(command -v appimagetool 2>/dev/null || echo "$HOME/.local/bin/appimagetool")"

if [ "${ARCH}" = "x86_64" ] && [ -x "${LINUXDEPLOY_X86}" ] && [ -x "${APPIMAGETOOL_X86}" ]; then
    "${LINUXDEPLOY_X86}" --appdir "${APPDIR}" --plugin gtk || true
    ARCH=x86_64 "${APPIMAGETOOL_X86}" "${APPDIR}" "${ROOT}/build/SonusGrid-x86_64.AppImage"
    echo "Built: ${ROOT}/build/SonusGrid-x86_64.AppImage"
elif [ "${ARCH}" = "aarch64" ] && [ -x "${APPIMAGETOOL_X86}" ]; then
    # No linuxdeploy step on aarch64: AppDir relies on target's distro for
    # GTK/python. The SonusGrid binaries themselves are self-contained Rust
    # statics with only libc + libasound dependencies.
    ARCH=aarch64 "${APPIMAGETOOL_X86}" "${APPDIR}" "${ROOT}/build/SonusGrid-aarch64.AppImage"
    echo "Built: ${ROOT}/build/SonusGrid-aarch64.AppImage"
else
    echo "appimagetool/linuxdeploy not found in PATH or ~/.local/bin." >&2
    echo "Install with:" >&2
    echo "  curl -L -o ~/.local/bin/linuxdeploy https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage" >&2
    echo "  curl -L -o ~/.local/bin/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" >&2
    echo "  chmod +x ~/.local/bin/{linuxdeploy,appimagetool}" >&2
    exit 1
fi
