# FAQ — SonusGrid

(English mirror.)

## Is this legal?

Reverse engineering for interoperability is legal under most jurisdictions:
- US: DMCA §1201(f)
- EU: Directive 2009/24/EC art. 6
- Brazil: Lei do Software 9.609/98 art. 6º

SonusGrid implements the Dante protocol independently, based on open-source
projects (mainly [Inferno](https://github.com/teodly/inferno)) and packet
captures. No proprietary Audinate code is copied.

## Can you call this "Dante for Linux"?

No. "Dante" is a registered trademark of Audinate Pty Ltd. The product is
named **SonusGrid**. The Audinate trademark only appears in descriptive text
("compatible with Dante audio networks") — permitted under fair use /
descriptive-trademark doctrines.

## Why GPL? Can I use this commercially?

Yes. GPLv3 does not forbid commercial use. **Distributing modified versions**
must publish modifications.

The GPLv3 obligation comes from Inferno (SonusGrid's audio plane dependency) —
it's a technical chain, not a SonusGrid choice.

If you only use it (install and run), do whatever you want. If you modify
and distribute, the modifications must be GPLv3.

## Should I use this in a critical production environment?

Cautiously. The stack is "alpha-but-usable" (per Inferno upstream). Known
limitations:
- No AES67 (Dante-only).
- No Dante Domain Manager (DDM).
- Multicast RX has known bugs.
- PTP on a non-RT kernel has higher jitter than RT.

Recommendation: run a one-week regression test before depending on it. Keep
official Windows DVS as a fallback in critical chains.

## Does it support the secondary network (Primary/Secondary redundancy)?

Not yet. SonusGrid uses a single interface and shows up as a "primary-only" device — it works on a
redundant network, just without redundancy for the PC itself. What is missing, what blocks it (a
two-port device is needed to capture the protocol) and how to help are in
[ROADMAP.md](../ROADMAP.md). Dante defines exactly two networks; there is no third.

## Does it work with Dante Via?

Yes, at the audio-transport level (RX/TX channels appear in matrix).
Via-specific features (USB device discovery, headphone routing) are not
implemented.

## Which sample rates are supported?

44.1, 48, 88.2, 96 kHz. 192 kHz works but is sparsely tested.

## How do I contribute?

GitHub. Issues + PRs. Current focus: stability and hardware coverage.

## Does the name "Inferno" appear anywhere user-visible?

**No.** "Inferno" is just the internal Rust library that does the Dante
protocol work. In the product:

- **Dante Controller** shows whatever `[device].name` is set in
  `~/.config/sonusgrid/config.toml` — default **`SonusGrid-Virtual`**.
- **App menu / GUI / .desktop**: all "SonusGrid".
- **Terminal commands**: `sonusgrid`, `sonusgrid-gtk`.
- **Package**: `sonusgrid_*.deb` or `SonusGrid-x86_64.AppImage`.
- **systemd journal**: `sonusgrid-clock.service`, `sonusgrid-audio.service`.

The only place "inferno" surfaces is in verbose runtime logs
(`sonusgrid logs -f`), because the engine writes those — equivalent to seeing
"kernel" in dmesg. It's the engine name, not the product name.

## Why use Inferno at all?

**Because writing it from scratch would take 6+ months of one developer's
time**, and Inferno already exists, is GPL, is maintained, and works. A
clean-room rewrite would involve: reverse-engineering Dante's ARC/CMC/DBC
protocols (weeks), implementing PTP-aligned RTP TX/RX (weeks), Dante-flavor
mDNS (days), interop testing across hardware vendors (months).

Inferno already did all of that. SonusGrid is the **product layer** (CLI, GUI,
installer, PipeWire/systemd integration); Inferno is the **transport
engine**. Just like Firefox uses SpiderMonkey for JS, VS Code uses Electron
for the browser engine, SonusGrid uses Inferno for the Dante engine.

You could fork it as `sonusgrid-engine` later if you want — but that's
unnecessary for anything the user sees.

## How do I report a bug?

Open a GitHub issue with:
1. Full `sonusgrid doctor` output.
2. Version (`sonusgrid version`).
3. Distro (`lsb_release -a`).
4. Expected vs observed behavior.

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
