# Install — SonusGrid

(English mirror; primary docs are in Portuguese under `docs/`.)

## Hardware prerequisites

- Gigabit switch (unmanaged is fine; if managed, enable IGMP snooping **with a querier**).
- At least one Dante device on the network.
- A **dedicated Ethernet NIC** on the Linux box. **Wi-Fi will not work** with Dante.
- A Windows/macOS PC running **Dante Controller** on the same subnet, to route channels.

## Software prerequisites

- **Ubuntu 24.04+, Debian 12+ (13 for the GUI), Linux Mint 22+, Fedora 40+, Arch.**
  Ubuntu 22.04 is **not** supported (PipeWire 0.3.48 < 0.3.65).
- PipeWire with `pipewire-pulse`, `pipewire-jack`, WirePlumber; systemd user session.
- GUI: Python 3.11+, GTK 4.12+, libadwaita 1.5+ (pulled in automatically).

## Path A — one command (Debian / Ubuntu / Mint) — recommended

```bash
curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
```

Downloads `SHA256SUMS` and the `.run` installer for your architecture from the latest
release, verifies it and runs it. Options are forwarded: `… | bash -s -- --no-launch`,
`… | bash -s -- --uninstall`. Pin a version with `SONUSGRID_VERSION=v0.3.0`.

## Path B — the `.run` installer

Download `SonusGrid-<version>-amd64.run` (or `-arm64.run`) from
[Releases](https://github.com/chrisvalezi/sonusgrid/releases), then:

```bash
chmod +x SonusGrid-*.run && ./SonusGrid-*.run
```

Run it as your normal user. It checks distro/arch, asks for your password **once**, installs
the `.deb` plus `pipewire-jack`, `wireplumber`, `pavucontrol` via `apt` (the package's postinst
does `setcap`, the udev rule and the PipeWire-JACK `ld.so.conf.d` drop-in), adds you to the
`audio` group (log out/in afterwards), creates the config, runs `sonusgrid doctor` and offers
to open the GUI. Options: `-- --yes --no-launch`, `-- --deb-only`, `-- --uninstall [--purge]`;
`--check` verifies the embedded checksum.

Double-click works in Nemo, Dolphin and Thunar; **GNOME Files ≥ 43 does not execute scripts** —
use a terminal or Path A. Verify downloads with `sha256sum -c --ignore-missing SHA256SUMS`.

## Path C — plain `.deb`

```bash
sudo apt install ./sonusgrid_<version>-1_amd64.deb pipewire-jack
sudo usermod -aG audio $USER        # then log out/in
sonusgrid doctor
```

## Path D — repository `install.sh` (Fedora / Arch / openSUSE / development)

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git && cd sonusgrid
./install.sh
```

## First configuration

The **network interface is mandatory** (there is no "auto", so you never bind to Wi-Fi by
accident).

- **GUI**: SonusGrid → *Configuration* → *Network interface* → **Apply**.
- **Terminal**: `sonusgrid config edit` → `[network] interface = "enp3s0"`.

Then:

```bash
sonusgrid doctor
sonusgrid start
sonusgrid status
```

The first `start` enables `sonusgrid-clock.service` and `sonusgrid-audio.service` in your
user session; they come up on login from then on.

## Uninstall

```bash
./SonusGrid-*.run -- --uninstall [--purge]   # or: curl … | bash -s -- --uninstall
sudo apt remove sonusgrid
./uninstall.sh [--purge]                     # from the repository
```

## Build from source

```bash
sudo apt install build-essential pkg-config libasound2-dev libpulse-dev \
     libjack-jackd2-dev python3 devscripts debhelper
make build        # statime + engine + cli + bridge + gui
make test
make deb          # dist/sonusgrid_<v>-1_<arch>.deb
make run-installer # dist/SonusGrid-<v>-<arch>.run
make release      # deb + run + SHA256SUMS
sudo make install # alternative to the .deb (then do the system setup by hand, see PT docs)
make deb-arm64    # cross-compile (Docker + cross)
make appimage     # experimental
```

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
