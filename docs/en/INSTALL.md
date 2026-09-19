# Install — SonusGrid

(English mirror; primary docs are in Portuguese under `docs/`.)

## Hardware prerequisites

- Gigabit switch (unmanaged is fine; if managed, enable IGMP snooping **with a querier**).
- At least one Dante device on the network.
- A **dedicated Ethernet NIC** on the Linux box. **Wi-Fi will not work** with Dante.
- A Windows/macOS PC running **Dante Controller** on the same subnet, to route channels.

## Software prerequisites

- PipeWire ≥ 0.3.65 with `pipewire-pulse` and `pipewire-jack`.
- systemd (the services are user units).
- Python 3.10+, GTK 4, libadwaita (GUI) — pulled in automatically.

## Path A — `install.sh` (recommended)

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git
cd sonusgrid
./install.sh
```

Run it as your normal user (it calls `sudo` only where needed). It detects the distro,
installs dependencies, builds/installs the `.deb` on Debian-family systems (or `make
install`s from source elsewhere and performs the same system setup: `setcap` on Statime,
udev rule for `/dev/ptp*`, `ld.so.conf.d` drop-in so `libjack` resolves to PipeWire-JACK),
adds you to the `audio` group and runs `sonusgrid doctor`.

Options: `--build`, `--deb FILE.deb`, `--no-start`.

## Path B — prebuilt `.deb`

```bash
sudo apt install ./sonusgrid_0.2.1-1_amd64.deb     # or _arm64.deb
sudo usermod -aG audio $USER                       # then log out/in
sonusgrid doctor
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
./uninstall.sh            # keeps ~/.config/sonusgrid
./uninstall.sh --purge
```

## Build from source

```bash
sudo apt install build-essential pkg-config libasound2-dev libpulse-dev \
     libjack-jackd2-dev python3 devscripts debhelper
make build        # statime + engine + cli + bridge + gui
make test
make deb          # dist/sonusgrid_<v>-1_amd64.deb
sudo make install # alternative to the .deb (then do the system setup by hand, see PT docs)
make deb-arm64    # cross-compile (Docker + cross)
make appimage     # experimental
```

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
