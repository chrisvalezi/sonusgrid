# Packaging & release pipeline

```
make build ──► make deb ──► make run-installer ──► make checksums
   │              │                 │                    │
   │   dist/sonusgrid_V-1_ARCH.deb  dist/SonusGrid-V-ARCH.run   dist/SHA256SUMS
   └── (make release = all of the above)
```

| Directory | Purpose |
|---|---|
| `debian/` | `.deb` metadata + maintainer scripts. `postinst` grants Statime its capabilities, installs the PipeWire-JACK `ld.so.conf.d` drop-in, reloads udev. |
| `makeself/` | End-user `.run` installer (vendored makeself + `setup.sh`/`root-steps.sh`). See its README. |
| `bootstrap/` | `install.sh` published as a release asset; the `curl … | bash` one-liner. It downloads `SHA256SUMS`, picks the `.run` for the host arch, verifies and runs it. |
| `udev/` | `60-sonusgrid-ptp.rules` — `audio` group access to `/dev/ptp*`. |
| `appimage/` | Experimental, not built by CI. |

## Release checklist

1. `make bump VERSION=x.y.z` — updates `version.mk`, both `Cargo.toml`,
   `packaging/debian/changelog`, `CHANGELOG.md` (fill in the section), metainfo.
2. `make check-version` — all green.
3. `git commit -am "Release x.y.z" && git tag -a vx.y.z -m "SonusGrid x.y.z" && git push --follow-tags`
4. GitHub Actions `Release` builds in `debian:bookworm` on amd64 and arm64 runners,
   generates `SHA256SUMS`, and publishes: 2 × `.deb`, 2 × `.run`, `install.sh`, `SHA256SUMS`.
   Tags with a suffix (`v0.3.0-rc1`) become **pre-releases**, so `releases/latest` never
   points at them — use them to rehearse.
5. Verify: `curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash`

## Testing the installer locally

```bash
make release
# in a throwaway container (no systemd/PipeWire there — only install/deps/postinst are exercised):
docker run --rm -it -v "$PWD/dist:/dist:ro" ubuntu:24.04 bash -c '
  apt-get update && apt-get install -y sudo && useradd -m t && echo "t ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/t
  cp /dist/SonusGrid-*.run /tmp/ && chmod +x /tmp/*.run
  su t -c "/tmp/SonusGrid-*.run -- --yes --no-launch"
  getcap /usr/libexec/sonusgrid/statime; id t; su t -c "sonusgrid doctor"; true'
# bootstrap script against local files:
SONUSGRID_BASE_URL=file://$PWD/dist bash packaging/bootstrap/install.sh -- --yes --no-launch
```

Minimum supported targets (set by the `debian:bookworm` build container and the
`pipewire >= 0.3.65` / `libadwaita >= 1.5` dependencies): Debian 12 (CLI) / 13 (GUI),
Ubuntu 24.04, Linux Mint 22, Raspberry Pi OS bookworm 64-bit.
