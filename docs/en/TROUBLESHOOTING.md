# Troubleshooting — SonusGrid

Always start with:

```bash
sonusgrid doctor
sonusgrid status
sonusgrid logs -f
```

## Won't start / "failed to start"

Since 0.2.1 `sonusgrid start` validates the config, clears systemd's *failed* state, starts
and then **verifies** both services, printing the journal tail on failure. Common causes:

| Log line | Cause | Fix |
|---|---|---|
| `network.interface is empty` | no NIC chosen | GUI → Configuration → Network interface → Apply |
| `Interface 'X' does not exist` | wrong name | `ip -br addr`, then `sonusgrid config edit` |
| `waiting for enpXsY to get an IPv4 address…` | cable unplugged / slow DHCP | plug it in; the service waits up to 45 s and keeps retrying every 3 s |
| `failed to create usrvclock server: Permission denied` (≤ 0.2.0 only) | broken `/tmp` perms | upgrade to ≥ 0.2.1 (sockets now live in `$XDG_RUNTIME_DIR/sonusgrid`) |
| `opening pulse Simple for record … Timeout` | PipeWire hung/degraded | `systemctl --user restart pipewire pipewire-pulse wireplumber`, then `sonusgrid start` |
| `no clock available (timeout …)` | bridge started before PTP lock | ≥ 0.2.1 waits for the lock; if it persists there is no PTP master on the LAN |
| `Start request repeated too quickly` (≤ 0.2.0 only) | systemd start-rate limit | `systemctl --user reset-failed sonusgrid-clock sonusgrid-audio` |

## "… is in 'failed' state"

`sonusgrid logs clock` (or `audio`) to see why, then `sonusgrid start`.

## "Could not query systemd --user"

You are in a shell without a user session (`sudo`, `su`, headless SSH). Run the commands
as **your** user in a normal session, or export `XDG_RUNTIME_DIR=/run/user/$(id -u)` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.

## "User is not in the 'audio' group"

`sudo usermod -aG audio $USER`, then log out/in. Needed for the hardware PTP clock
(`/dev/ptp0`); without it Statime falls back to a software clock.

## "statime missing cap_sys_time"

```bash
sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep /usr/libexec/sonusgrid/statime
```

## "pipewire is using N MB of RAM — looks degraded"

We have seen `pipewire` reach 2.7 GB and 30 % idle CPU while delivering no audio to any
client. Restart the stack (apps lose audio for ~1 s):

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber && sonusgrid start
```

## "…/00-sonusgrid-pipewire-jack.conf missing"

Without it `libjack.so.0` resolves to jackd2 and DAWs won't see the SonusGrid JACK client:

```bash
echo /usr/lib/x86_64-linux-gnu/pipewire-0.3/jack | sudo tee /etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf
sudo ldconfig && sonusgrid restart
```

## NTP (`systemd-timesyncd`, `chronyd`) — do I need to stop it?

**No.** Statime runs in *virtual-system-clock* mode (an overlay on `CLOCK_MONOTONIC_RAW`);
the system clock is never touched.

## Glitches / xruns

Raise `rx_latency_ns` / `tx_latency_ns` to 8 000 000 in the config and `sonusgrid restart`;
install a low-latency kernel; raise the JACK buffer in the GUI's Tools page.

## SonusGrid does not appear in Dante Controller

1. `sonusgrid status` — both services active.
2. `sonusgrid devices` / `avahi-browse -t -r _netaudio-cmc._udp`.
3. Same subnet as the Controller PC?
4. Firewall: allow UDP 319, 320, 4440, 4444, 4455, 5353, 8700, 8800 and the high RTP range
   on the Dante NIC.
5. Managed switch with IGMP snooping but no querier blocks multicast.

## Audacity won't open the "sonusgrid" device

Use `sonusgrid_stereo` (2-channel downmix) or record from the PipeWire source `SonusGrid_RX`.

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
