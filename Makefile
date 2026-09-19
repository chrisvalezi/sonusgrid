include version.mk

PREFIX        ?= /usr
DESTDIR       ?=
CARGO         ?= cargo
PYTHON        ?= python3

# TARGET selects the Cargo target triple. Empty = native build (default
# x86_64 on most CI). For ARM64 use TARGET=aarch64-unknown-linux-gnu, which
# also flips the install paths (libdir, deb arch, AppImage suffix).
TARGET        ?=

HOST_DEB_ARCH := $(shell dpkg --print-architecture 2>/dev/null || echo amd64)
HOST_MULTIARCH := $(shell dpkg-architecture -qDEB_HOST_MULTIARCH 2>/dev/null || echo x86_64-linux-gnu)

ifeq ($(TARGET),)
    NATIVE_BUILD := 1
    CARGO_TARGET_DIR_SUFFIX :=
    LIBDIR        := lib/$(HOST_MULTIARCH)
    DEB_ARCH      := $(HOST_DEB_ARCH)
    APPIMG_ARCH   := $(if $(filter arm64,$(HOST_DEB_ARCH)),aarch64,x86_64)
    CROSS         := $(CARGO)
else
    NATIVE_BUILD :=
    CARGO_TARGET_DIR_SUFFIX := /$(TARGET)
    DEB_ARCH := $(if $(filter aarch64-unknown-linux-gnu,$(TARGET)),arm64,$(if $(filter armv7-unknown-linux-gnueabihf,$(TARGET)),armhf,unknown))
    LIBDIR   := $(if $(filter aarch64-unknown-linux-gnu,$(TARGET)),lib/aarch64-linux-gnu,$(if $(filter armv7-unknown-linux-gnueabihf,$(TARGET)),lib/arm-linux-gnueabihf,lib))
    APPIMG_ARCH := $(if $(filter aarch64-unknown-linux-gnu,$(TARGET)),aarch64,$(if $(filter armv7-unknown-linux-gnueabihf,$(TARGET)),armhf,unknown))
    CROSS         := cross
endif

CLI_BIN       := crates/sonus-cli/target$(CARGO_TARGET_DIR_SUFFIX)/release/sonusgrid
BRIDGE_BIN    := crates/sonusgrid-bridge/target$(CARGO_TARGET_DIR_SUFFIX)/release/sonusgrid-bridge
ENGINE_DIR    := crates/sonusgrid-engine
INFERNO_LIB   := $(ENGINE_DIR)/target$(CARGO_TARGET_DIR_SUFFIX)/release/libasound_module_pcm_sonusgrid.so
STATIME_BIN   := vendor/statime/target$(CARGO_TARGET_DIR_SUFFIX)/release/statime
INFERNO2PIPE  := $(ENGINE_DIR)/target$(CARGO_TARGET_DIR_SUFFIX)/release/sonusgrid_pipe

DEB_NAME      := sonusgrid_$(SONUS_VERSION)-$(DEB_REVISION)_$(DEB_ARCH).deb
RUN_NAME      := SonusGrid-$(SONUS_VERSION)-$(DEB_ARCH).run
APPIMG_NAME   := SonusGrid-$(APPIMG_ARCH).AppImage

# Helper: pass --target to the cargo invocation only when TARGET is set.
CARGO_TARGET_FLAG := $(if $(TARGET),--target=$(TARGET),)

.PHONY: help build build-vendor build-cli build-gui test deb deb-arm64 \
        run-installer checksums release check-version bump \
        appimage appimage-arm64 docs docs-html install uninstall clean \
        distclean version build-all-arch macos-cross-check macos-cli-universal \
        macos-statime-universal macos-inferno-c-universal

help:
	@echo "SonusGrid build system — version $(SONUS_VERSION)"
	@echo
	@echo "Native targets (host = $(shell uname -m)):"
	@echo "  make build         — build everything for the host"
	@echo "  make deb           — build dist/$(DEB_NAME)"
	@echo "  make run-installer — build dist/$(RUN_NAME) (end-user self-extracting installer)"
	@echo "  make release       — deb + run-installer + dist/SHA256SUMS"
	@echo "  make appimage      — build $(APPIMG_NAME) (experimental)"
	@echo
	@echo "Cross-compile (needs Docker + cross-rs):"
	@echo "  make deb-arm64        — build sonusgrid_$(SONUS_VERSION)-$(DEB_REVISION)_arm64.deb"
	@echo "  make appimage-arm64   — build SonusGrid-aarch64.AppImage"
	@echo "  make build-all-arch   — build deb + appimage for amd64 AND arm64"
	@echo
	@echo "macOS (Linux side — runs cargo check; full build needs a Mac):"
	@echo "  make macos-cross-check       — cargo check sonus-cli + inferno-c + statime-macos"
	@echo "                                 for aarch64-apple-darwin AND x86_64-apple-darwin"
	@echo
	@echo "Other:"
	@echo "  make build-vendor  — build statime and inferno"
	@echo "  make build-cli     — build the sonus CLI"
	@echo "  make build-gui     — byte-compile the GTK GUI"
	@echo "  make test          — unit + smoke tests"
	@echo "  make bump VERSION=x.y.z — bump every version string + changelog stanza"
	@echo "  make check-version TAG=vx.y.z — verify all version strings match the tag"
	@echo "  make docs-html     — render docs to HTML"
	@echo "  make install       — install into PREFIX (default /usr)"
	@echo "  make uninstall     — undo install"
	@echo "  make clean         — remove build artefacts"

version:
	@echo $(SONUS_VERSION)

build: build-vendor build-cli build-gui

build-vendor: $(STATIME_BIN) $(INFERNO_LIB)

$(STATIME_BIN):
	cd vendor/statime && $(CROSS) build --release $(CARGO_TARGET_FLAG)

$(INFERNO_LIB):
	cd $(ENGINE_DIR) && $(CROSS) build --release $(CARGO_TARGET_FLAG)

build-cli: $(CLI_BIN) $(BRIDGE_BIN)

$(CLI_BIN): $(wildcard crates/sonus-cli/src/*.rs) crates/sonus-cli/Cargo.toml
	cd crates/sonus-cli && $(CROSS) build --release $(CARGO_TARGET_FLAG)

$(BRIDGE_BIN): $(wildcard crates/sonusgrid-bridge/src/*.rs) crates/sonusgrid-bridge/Cargo.toml
	cd crates/sonusgrid-bridge && $(CROSS) build --release $(CARGO_TARGET_FLAG)

build-gui:
	printf '__version__ = "%s"\n' $(SONUS_VERSION) > gui/sonus-gtk/sonus_gtk/_version.py
	find gui/sonus-gtk/sonus_gtk -name __pycache__ -type d -prune -exec rm -rf {} +
	$(PYTHON) -m compileall -q gui/sonus-gtk/sonus_gtk

test:
	cd crates/sonus-cli && $(CARGO) test
	bash tests/smoke/cli.sh

deb: build
	@command -v dpkg-buildpackage >/dev/null || { echo "install: sudo apt install devscripts debhelper"; exit 1; }
	@rm -rf build/debian
	@mkdir -p build
	cp -r packaging/debian build/debian
	cd build && \
	    SONUS_SOURCE_DIR=$(CURDIR) \
	    SONUS_TARGET=$(TARGET) \
	    SONUS_LIBDIR=$(LIBDIR) \
	    PATH=$$HOME/.cargo/bin:$$PATH \
	    dpkg-buildpackage -us -uc -b -d -a$(DEB_ARCH)
	@mkdir -p dist
	@mv -f $(CURDIR)/sonusgrid_$(SONUS_VERSION)-$(DEB_REVISION)_$(DEB_ARCH).* dist/ 2>/dev/null || true
	@mv -f $(CURDIR)/sonusgrid-dbgsym_$(SONUS_VERSION)-$(DEB_REVISION)_$(DEB_ARCH).ddeb dist/ 2>/dev/null || true
	@echo "Built: dist/$(DEB_NAME)"

deb-arm64:
	$(MAKE) deb TARGET=aarch64-unknown-linux-gnu

# --- end-user installer + release bundle -----------------------------------
run-installer: deb
	bash packaging/makeself/build-run.sh $(SONUS_VERSION) $(DEB_REVISION) $(DEB_ARCH) dist/$(DEB_NAME) dist/$(RUN_NAME)

checksums:
	cd dist && sha256sum *.deb *.run > SHA256SUMS && cat SHA256SUMS

release: run-installer checksums

check-version:
	bash scripts/check-version.sh $(TAG)

bump:
	@test -n "$(VERSION)" || { echo "usage: make bump VERSION=x.y.z"; exit 1; }
	bash scripts/bump-version.sh $(VERSION)

appimage: build
	bash packaging/appimage/build-appimage.sh $(SONUS_VERSION) $(APPIMG_ARCH)

appimage-arm64:
	$(MAKE) appimage TARGET=aarch64-unknown-linux-gnu

build-all-arch: deb appimage deb-arm64 appimage-arm64

# --- macOS targets (Linux-side validation) -------------------------------
# These run `cargo check` for both Apple architectures so we catch breakage
# in the cfg-gated Mac code paths without needing a Mac. The actual build
# requires Xcode + Apple SDK; see macos/README.md.

macos-cross-check:
	@for crate in crates/sonus-cli crates/inferno-c macos/statime-macos; do \
	    for tgt in aarch64-apple-darwin x86_64-apple-darwin; do \
	        echo "==> cargo check $$crate ($$tgt)"; \
	        $(CARGO) check --manifest-path $$crate/Cargo.toml --target=$$tgt || exit 1; \
	    done; \
	done
	@echo "OK — sonus-cli, inferno-c, statime-macos all type-check for both Apple targets."

docs: docs-html

docs-html:
	@command -v pandoc >/dev/null || { echo "install: sudo apt install pandoc"; exit 1; }
	@mkdir -p build/docs
	@for f in docs/*.md docs/en/*.md; do \
	    [ -f "$$f" ] || continue; \
	    out=build/docs/$$(basename $$f .md).html; \
	    pandoc -s -f gfm -t html5 --metadata title="$$(basename $$f .md)" "$$f" -o "$$out"; \
	done

install: build
	install -Dm 0755 $(CLI_BIN) $(DESTDIR)$(PREFIX)/bin/sonusgrid
	install -Dm 0755 gui/sonus-gtk/sonusgrid-gtk.sh $(DESTDIR)$(PREFIX)/bin/sonusgrid-gtk
	install -Dm 0755 $(BRIDGE_BIN) $(DESTDIR)$(PREFIX)/libexec/sonusgrid/sonusgrid-bridge
	install -Dm 0755 $(STATIME_BIN) $(DESTDIR)$(PREFIX)/libexec/sonusgrid/statime
	install -Dm 0755 $(INFERNO2PIPE) $(DESTDIR)$(PREFIX)/libexec/sonusgrid/sonusgrid_pipe
	install -Dm 0755 $(INFERNO_LIB) $(DESTDIR)$(PREFIX)/$(LIBDIR)/alsa-lib/libasound_module_pcm_sonusgrid.so
	install -Dm 0644 systemd/sonusgrid-clock.service $(DESTDIR)$(PREFIX)/lib/systemd/user/sonusgrid-clock.service
	install -Dm 0644 systemd/sonusgrid-audio.service $(DESTDIR)$(PREFIX)/lib/systemd/user/sonusgrid-audio.service
	install -Dm 0644 systemd/sonusgrid-pipewire-clock.conf $(DESTDIR)$(PREFIX)/lib/systemd/user/pipewire.service.d/sonusgrid-clock.conf
	install -Dm 0644 packaging/udev/60-sonusgrid-ptp.rules $(DESTDIR)/usr/lib/udev/rules.d/60-sonusgrid-ptp.rules
	install -Dm 0644 packaging/limits.d/sonusgrid.conf $(DESTDIR)/etc/security/limits.d/sonusgrid.conf
	install -Dm 0644 alsa/sonusgrid.conf.in $(DESTDIR)$(PREFIX)/share/sonusgrid/sonusgrid.conf.in
	install -Dm 0644 gui/sonus-gtk/data/io.sonusgrid.SonusGrid.desktop $(DESTDIR)$(PREFIX)/share/applications/io.sonusgrid.SonusGrid.desktop
	install -Dm 0644 gui/sonus-gtk/data/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg
	install -Dm 0644 gui/sonus-gtk/data/icons/hicolor/symbolic/apps/io.sonusgrid.SonusGrid-symbolic.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/symbolic/apps/io.sonusgrid.SonusGrid-symbolic.svg
	for s in 16 24 32 48 64 128 256 512; do \
	    install -Dm 0644 gui/sonus-gtk/data/icons/hicolor/$${s}x$${s}/apps/io.sonusgrid.SonusGrid.png $(DESTDIR)$(PREFIX)/share/icons/hicolor/$${s}x$${s}/apps/io.sonusgrid.SonusGrid.png; \
	done
	install -Dm 0644 gui/sonus-gtk/data/io.sonusgrid.SonusGrid.metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/io.sonusgrid.SonusGrid.metainfo.xml
	mkdir -p $(DESTDIR)$(PREFIX)/share/sonusgrid/gui
	cp -r gui/sonus-gtk/sonus_gtk $(DESTDIR)$(PREFIX)/share/sonusgrid/gui/
	install -Dm 0644 docs/USER_GUIDE.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/USER_GUIDE.md
	install -Dm 0644 docs/DAW.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/DAW.md
	install -Dm 0644 docs/FAQ.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/FAQ.md
	install -Dm 0644 docs/TROUBLESHOOTING.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/TROUBLESHOOTING.md
	install -Dm 0644 docs/INSTALL.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/INSTALL.md
	install -Dm 0644 docs/en/USER_GUIDE.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/en/USER_GUIDE.md
	install -Dm 0644 docs/en/FAQ.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/en/FAQ.md
	install -Dm 0644 docs/en/TROUBLESHOOTING.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/en/TROUBLESHOOTING.md
	install -Dm 0644 docs/en/INSTALL.md $(DESTDIR)$(PREFIX)/share/doc/sonusgrid/en/INSTALL.md
	@if [ "$(DESTDIR)" = "" ] && [ "$(NATIVE_BUILD)" = "1" ] && command -v setcap >/dev/null; then \
	    setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep $(DESTDIR)$(PREFIX)/libexec/sonusgrid/statime || true; \
	fi

uninstall:
	rm -f $(DESTDIR)$(PREFIX)/bin/sonusgrid $(DESTDIR)$(PREFIX)/bin/sonusgrid-gtk $(DESTDIR)$(PREFIX)/libexec/sonusgrid/sonusgrid-bridge
	rm -rf $(DESTDIR)$(PREFIX)/libexec/sonusgrid
	rm -f $(DESTDIR)$(PREFIX)/$(LIBDIR)/alsa-lib/libasound_module_pcm_sonusgrid.so
	rm -f $(DESTDIR)$(PREFIX)/lib/systemd/user/sonusgrid-clock.service
	rm -f $(DESTDIR)$(PREFIX)/lib/systemd/user/sonusgrid-audio.service
	rm -f $(DESTDIR)$(PREFIX)/lib/systemd/user/pipewire.service.d/sonusgrid-clock.conf
	rm -f $(DESTDIR)/usr/lib/udev/rules.d/60-sonusgrid-ptp.rules
	rm -f $(DESTDIR)/etc/security/limits.d/sonusgrid.conf
	rm -rf $(DESTDIR)$(PREFIX)/share/sonusgrid
	rm -rf $(DESTDIR)$(PREFIX)/share/doc/sonusgrid
	rm -f $(DESTDIR)$(PREFIX)/share/applications/io.sonusgrid.SonusGrid.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/symbolic/apps/io.sonusgrid.SonusGrid-symbolic.svg
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/*/apps/io.sonusgrid.SonusGrid.png
	rm -f $(DESTDIR)$(PREFIX)/share/metainfo/io.sonusgrid.SonusGrid.metainfo.xml

clean:
	cd crates/sonus-cli && $(CARGO) clean
	cd crates/sonusgrid-bridge && $(CARGO) clean
	rm -rf build dist

distclean: clean
	cd vendor/statime && $(CARGO) clean
	cd $(ENGINE_DIR) && $(CARGO) clean
