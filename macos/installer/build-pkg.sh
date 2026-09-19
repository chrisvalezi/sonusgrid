#!/usr/bin/env bash
# build-pkg.sh — assemble the SonusGrid .pkg installer for macOS.
#
# Run on a Mac with Xcode CLI tools and a Developer ID certificate. From the
# project root:
#
#   bash macos/installer/build-pkg.sh 0.3.0 [arm64|x86_64|universal]
#
# Produces:
#   build/SonusGrid-<version>-<arch>.pkg  (signed + notarized)
#
# Pre-requisites (read once):
#   - Apple Developer Program member ($99/yr)
#   - "Developer ID Application" cert in your keychain (signs .app, .driver)
#   - "Developer ID Installer"   cert in your keychain (signs .pkg)
#   - App-specific password stored as a keychain item named "AC_PASSWORD"
#     (xcrun notarytool store-credentials AC_PASSWORD ...)

set -euo pipefail

VERSION="${1:-0.3.0}"
ARCH="${2:-universal}"
ROOT="$(cd "$(dirname "${0}")/../.." && pwd)"
BUILD="${ROOT}/build/macos-${ARCH}"
ROOT_DIR="${BUILD}/root"

DEV_ID_APP="${SONUSGRID_DEV_ID_APP:-Developer ID Application}"
DEV_ID_INSTALLER="${SONUSGRID_DEV_ID_INSTALLER:-Developer ID Installer}"
TEAM_ID="${SONUSGRID_TEAM_ID:-}"
NOTARY_PROFILE="${SONUSGRID_NOTARY_PROFILE:-AC_PASSWORD}"

[ -n "${TEAM_ID}" ] || { echo "ERROR: set SONUSGRID_TEAM_ID env var" >&2; exit 1; }

if [ "$(uname -s)" != "Darwin" ]; then
    echo "ERROR: this script must run on macOS." >&2
    exit 1
fi

# 1. Build Universal Binary versions of the Rust components --------------
mkdir -p "${ROOT_DIR}"

echo "==> 1/6  build sonusgrid CLI (universal)"
cargo build --release --manifest-path "${ROOT}/crates/sonus-cli/Cargo.toml" \
    --target aarch64-apple-darwin
cargo build --release --manifest-path "${ROOT}/crates/sonus-cli/Cargo.toml" \
    --target x86_64-apple-darwin
mkdir -p "${ROOT_DIR}/usr/local/bin"
lipo -create -output "${ROOT_DIR}/usr/local/bin/sonusgrid" \
    "${ROOT}/crates/sonus-cli/target/aarch64-apple-darwin/release/sonusgrid" \
    "${ROOT}/crates/sonus-cli/target/x86_64-apple-darwin/release/sonusgrid"

echo "==> 2/6  build statime-macos (universal)"
cargo build --release --manifest-path "${ROOT}/macos/statime-macos/Cargo.toml" \
    --target aarch64-apple-darwin
cargo build --release --manifest-path "${ROOT}/macos/statime-macos/Cargo.toml" \
    --target x86_64-apple-darwin
mkdir -p "${ROOT_DIR}/usr/local/libexec/sonusgrid"
lipo -create -output "${ROOT_DIR}/usr/local/libexec/sonusgrid/statime-macos" \
    "${ROOT}/macos/statime-macos/target/aarch64-apple-darwin/release/statime-macos" \
    "${ROOT}/macos/statime-macos/target/x86_64-apple-darwin/release/statime-macos"

echo "==> 3/6  build inferno-c dylib (universal)"
cargo build --release --manifest-path "${ROOT}/crates/inferno-c/Cargo.toml" \
    --target aarch64-apple-darwin
cargo build --release --manifest-path "${ROOT}/crates/inferno-c/Cargo.toml" \
    --target x86_64-apple-darwin
mkdir -p "${BUILD}/inferno-c-universal"
lipo -create -output "${BUILD}/inferno-c-universal/libinferno_c.dylib" \
    "${ROOT}/crates/inferno-c/target/aarch64-apple-darwin/release/libinferno_c.dylib" \
    "${ROOT}/crates/inferno-c/target/x86_64-apple-darwin/release/libinferno_c.dylib"

echo "==> 4/6  build HAL plugin bundle (Xcode)"
xcodebuild -project "${ROOT}/macos/halplugin/SonusGridHAL.xcodeproj" \
    -scheme SonusGridHAL -configuration Release \
    ARCHS="arm64 x86_64" ONLY_ACTIVE_ARCH=NO \
    CODE_SIGN_IDENTITY="${DEV_ID_APP}" \
    DEVELOPMENT_TEAM="${TEAM_ID}" \
    OTHER_CODE_SIGN_FLAGS="--options=runtime --timestamp" \
    BUILT_PRODUCTS_DIR="${BUILD}/halplugin"
mkdir -p "${ROOT_DIR}/Library/Audio/Plug-Ins/HAL"
cp -r "${BUILD}/halplugin/SonusGridHAL.bundle" \
    "${ROOT_DIR}/Library/Audio/Plug-Ins/HAL/SonusGrid.driver"
mkdir -p "${ROOT_DIR}/Library/Audio/Plug-Ins/HAL/SonusGrid.driver/Contents/Frameworks"
cp "${BUILD}/inferno-c-universal/libinferno_c.dylib" \
    "${ROOT_DIR}/Library/Audio/Plug-Ins/HAL/SonusGrid.driver/Contents/Frameworks/"

echo "==> 5/6  build SonusGrid.app (Xcode)"
xcodebuild -project "${ROOT}/macos/app/SonusGrid.xcodeproj" \
    -scheme SonusGrid -configuration Release \
    ARCHS="arm64 x86_64" ONLY_ACTIVE_ARCH=NO \
    CODE_SIGN_IDENTITY="${DEV_ID_APP}" \
    DEVELOPMENT_TEAM="${TEAM_ID}" \
    OTHER_CODE_SIGN_FLAGS="--options=runtime --timestamp" \
    BUILT_PRODUCTS_DIR="${BUILD}/app"
mkdir -p "${ROOT_DIR}/Applications"
cp -r "${BUILD}/app/SonusGrid.app" "${ROOT_DIR}/Applications/"

# launchd plist
mkdir -p "${ROOT_DIR}/Library/LaunchDaemons"
install -m 0644 "${ROOT}/macos/launchd/io.sonusgrid.clock.plist" \
    "${ROOT_DIR}/Library/LaunchDaemons/"

# default config
mkdir -p "${ROOT_DIR}/etc/sonusgrid"
cat > "${ROOT_DIR}/etc/sonusgrid/clock.toml" <<EOF
loglevel = "info"
domain = 0
priority1 = 251
virtual_system_clock = true
usrvclock_export = true
usrvclock_socket = "/var/run/sonusgrid/usrvclock"
[[port]]
interface = "en0"
network_mode = "ipv4"
hardware_clock = "auto"
protocol_version = "PTPv1"
EOF

echo "==> 6/6  productbuild + sign + notarize"
PKG_UNSIGNED="${BUILD}/SonusGrid-${VERSION}-${ARCH}.unsigned.pkg"
PKG_SIGNED="${ROOT}/build/SonusGrid-${VERSION}-${ARCH}.pkg"

pkgbuild --root "${ROOT_DIR}" \
    --identifier io.sonusgrid.SonusGrid \
    --version "${VERSION}" \
    --install-location / \
    --scripts "${ROOT}/macos/installer/scripts" \
    --sign "${DEV_ID_INSTALLER}" \
    "${PKG_UNSIGNED}"

productbuild --distribution "${ROOT}/macos/installer/distribution.xml" \
    --resources "${ROOT}/macos/installer" \
    --package-path "${BUILD}" \
    --sign "${DEV_ID_INSTALLER}" \
    "${PKG_SIGNED}"

xcrun notarytool submit "${PKG_SIGNED}" --keychain-profile "${NOTARY_PROFILE}" --wait
xcrun stapler staple "${PKG_SIGNED}"

echo
echo "Built: ${PKG_SIGNED}"
echo "Verify: pkgutil --check-signature ${PKG_SIGNED}"
