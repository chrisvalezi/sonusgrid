// SPDX-License-Identifier: GPL-3.0-or-later
//! Tiny mDNS browser for Dante devices.
//!
//! Sends a single PTR query for `_netaudio-arc._udp.local` on the configured
//! interface and collects answers for a couple of seconds. Every Dante
//! endpoint answers with its PTR + SRV + A records in one packet, which is
//! all we need for a "who's on the network" list. No Avahi dependency —
//! `avahi-browse` frequently returns nothing here because Avahi is not bound
//! to the audio NIC.
//!
//! The DNS decoder is deliberately minimal: names (with compression), PTR,
//! SRV and A records. Anything else is skipped by length.

use std::collections::BTreeMap;
use std::net::{Ipv4Addr, SocketAddrV4, UdpSocket};
use std::time::{Duration, Instant};

const MDNS_GROUP: Ipv4Addr = Ipv4Addr::new(224, 0, 0, 251);
const MDNS_PORT: u16 = 5353;
const SERVICE: &str = "_netaudio-arc._udp.local";

#[derive(Debug, Clone, serde::Serialize, PartialEq, Eq)]
pub struct DanteDevice {
    /// Instance name as advertised (e.g. `Genelec-8694bd`).
    pub name: String,
    /// IPv4 the device answered from (or its A record when present).
    pub ip: String,
    /// Hostname from the SRV record, without the trailing `.local`.
    pub host: String,
    /// True when this is the SonusGrid instance running on this machine.
    pub is_self: bool,
}

/// Browse for Dante devices. `bind_ip` selects the NIC (mDNS is link-local);
/// `self_name` marks our own advertisement.
pub fn browse(bind_ip: Ipv4Addr, self_name: &str, wait: Duration) -> std::io::Result<Vec<DanteDevice>> {
    // Responders answer to the multicast group on port 5353, so we must
    // listen there too (shared with Avahi via SO_REUSEADDR/REUSEPORT) and
    // join the group on the audio NIC. We also set the QU ("unicast
    // response requested") bit so well-behaved stacks answer us directly.
    let sock = bind_mdns_port()?;
    set_multicast_if(&sock, bind_ip)?;
    sock.join_multicast_v4(&MDNS_GROUP, &bind_ip)?;
    sock.set_multicast_ttl_v4(255)?;
    sock.set_read_timeout(Some(Duration::from_millis(250)))?;

    // Query: header (id 0, flags 0, 1 question) + QNAME + QTYPE PTR + QCLASS IN|QU.
    let mut q = vec![0u8, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0];
    encode_name(&mut q, SERVICE);
    q.extend_from_slice(&[0, 12, 0x80, 1]);
    // Send twice (first packet is occasionally lost while the switch learns us).
    sock.send_to(&q, SocketAddrV4::new(MDNS_GROUP, MDNS_PORT))?;
    std::thread::sleep(Duration::from_millis(80));
    let _ = sock.send_to(&q, SocketAddrV4::new(MDNS_GROUP, MDNS_PORT));

    let mut found: BTreeMap<String, DanteDevice> = BTreeMap::new();
    let mut buf = [0u8; 9000];
    let t0 = Instant::now();
    while t0.elapsed() < wait {
        let (n, from) = match sock.recv_from(&mut buf) {
            Ok(x) => x,
            Err(_) => continue,
        };
        let from_ip = match from {
            std::net::SocketAddr::V4(a) => *a.ip(),
            _ => continue,
        };
        for dev in parse_answers(&buf[..n], from_ip) {
            let is_self = dev.name.eq_ignore_ascii_case(self_name) || from_ip == bind_ip;
            found.entry(dev.name.clone()).or_insert(DanteDevice { is_self, ..dev });
        }
    }
    Ok(found.into_values().collect())
}

/// Bind 0.0.0.0:5353 with SO_REUSEADDR + SO_REUSEPORT so we can coexist
/// with Avahi / systemd-resolved, which already own that port.
fn bind_mdns_port() -> std::io::Result<UdpSocket> {
    use std::os::unix::io::FromRawFd;
    unsafe {
        let fd = libc::socket(libc::AF_INET, libc::SOCK_DGRAM | libc::SOCK_CLOEXEC, 0);
        if fd < 0 {
            return Err(std::io::Error::last_os_error());
        }
        let one: libc::c_int = 1;
        for opt in [libc::SO_REUSEADDR, libc::SO_REUSEPORT] {
            libc::setsockopt(
                fd,
                libc::SOL_SOCKET,
                opt,
                &one as *const _ as *const libc::c_void,
                std::mem::size_of::<libc::c_int>() as libc::socklen_t,
            );
        }
        let addr = libc::sockaddr_in {
            sin_family: libc::AF_INET as libc::sa_family_t,
            sin_port: MDNS_PORT.to_be(),
            sin_addr: libc::in_addr { s_addr: 0 },
            sin_zero: [0; 8],
        };
        if libc::bind(
            fd,
            &addr as *const _ as *const libc::sockaddr,
            std::mem::size_of::<libc::sockaddr_in>() as libc::socklen_t,
        ) != 0
        {
            let e = std::io::Error::last_os_error();
            libc::close(fd);
            return Err(e);
        }
        Ok(UdpSocket::from_raw_fd(fd))
    }
}

/// `IP_MULTICAST_IF`: std's UdpSocket has no setter for the outgoing
/// multicast interface, so go through libc.
fn set_multicast_if(sock: &UdpSocket, ip: Ipv4Addr) -> std::io::Result<()> {
    use std::os::unix::io::AsRawFd;
    let addr = libc::in_addr { s_addr: u32::from(ip).to_be() };
    let rc = unsafe {
        libc::setsockopt(
            sock.as_raw_fd(),
            libc::IPPROTO_IP,
            libc::IP_MULTICAST_IF,
            &addr as *const _ as *const libc::c_void,
            std::mem::size_of::<libc::in_addr>() as libc::socklen_t,
        )
    };
    if rc != 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

fn encode_name(out: &mut Vec<u8>, name: &str) {
    for label in name.split('.') {
        out.push(label.len() as u8);
        out.extend_from_slice(label.as_bytes());
    }
    out.push(0);
}

/// Decode a possibly-compressed DNS name at `pos`. Returns (name, next_pos).
fn read_name(pkt: &[u8], mut pos: usize) -> Option<(String, usize)> {
    let mut labels: Vec<String> = Vec::new();
    let mut jumped = false;
    let mut next = 0usize;
    let mut hops = 0;
    loop {
        let len = *pkt.get(pos)? as usize;
        if len == 0 {
            pos += 1;
            break;
        }
        if len & 0xC0 == 0xC0 {
            let ptr = ((len & 0x3F) << 8) | *pkt.get(pos + 1)? as usize;
            if !jumped {
                next = pos + 2;
            }
            jumped = true;
            pos = ptr;
            hops += 1;
            if hops > 16 {
                return None;
            }
            continue;
        }
        let label = pkt.get(pos + 1..pos + 1 + len)?;
        labels.push(String::from_utf8_lossy(label).to_string());
        pos += 1 + len;
    }
    Some((labels.join("."), if jumped { next } else { pos }))
}

fn parse_answers(pkt: &[u8], from_ip: Ipv4Addr) -> Vec<DanteDevice> {
    let mut out = Vec::new();
    if pkt.len() < 12 {
        return out;
    }
    if pkt[2] & 0x80 == 0 {
        return out; // a query (possibly our own echo), not a response
    }
    let qd = u16::from_be_bytes([pkt[4], pkt[5]]) as usize;
    let an = u16::from_be_bytes([pkt[6], pkt[7]]) as usize;
    let ns = u16::from_be_bytes([pkt[8], pkt[9]]) as usize;
    let ar = u16::from_be_bytes([pkt[10], pkt[11]]) as usize;
    let mut pos = 12;
    for _ in 0..qd {
        let Some((_, p)) = read_name(pkt, pos) else { return out };
        pos = p + 4;
    }
    let mut instances: Vec<String> = Vec::new(); // "Name._netaudio-arc._udp.local"
    let mut srv_host: BTreeMap<String, String> = BTreeMap::new(); // instance -> host
    let mut a_rec: BTreeMap<String, Ipv4Addr> = BTreeMap::new(); // host -> ip
    for _ in 0..(an + ns + ar) {
        let Some((name, p)) = read_name(pkt, pos) else { break };
        if p + 10 > pkt.len() {
            break;
        }
        let rtype = u16::from_be_bytes([pkt[p], pkt[p + 1]]);
        let rdlen = u16::from_be_bytes([pkt[p + 8], pkt[p + 9]]) as usize;
        let rd = p + 10;
        if rd + rdlen > pkt.len() {
            break;
        }
        match rtype {
            12 if name.eq_ignore_ascii_case(SERVICE) => {
                if let Some((inst, _)) = read_name(pkt, rd) {
                    instances.push(inst);
                }
            }
            33 => {
                // SRV: priority(2) weight(2) port(2) target
                if let Some((target, _)) = read_name(pkt, rd + 6) {
                    srv_host.insert(name.clone(), target);
                }
            }
            1 if rdlen == 4 => {
                a_rec.insert(name.clone(), Ipv4Addr::new(pkt[rd], pkt[rd + 1], pkt[rd + 2], pkt[rd + 3]));
            }
            _ => {}
        }
        pos = rd + rdlen;
    }
    for inst in instances {
        let short = inst
            .strip_suffix(&format!(".{SERVICE}"))
            .or_else(|| inst.strip_suffix(SERVICE))
            .unwrap_or(&inst)
            .trim_end_matches('.')
            .to_string();
        let host = srv_host.get(&inst).cloned().unwrap_or_default();
        let ip = host
            .as_str()
            .pipe(|h| a_rec.get(h).copied())
            .unwrap_or(from_ip);
        out.push(DanteDevice {
            name: short,
            ip: ip.to_string(),
            host: host.trim_end_matches(".local").to_string(),
            is_self: false,
        });
    }
    out
}

trait Pipe: Sized {
    fn pipe<R>(self, f: impl FnOnce(Self) -> R) -> R {
        f(self)
    }
}
impl<T> Pipe for T {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn name_roundtrip() {
        let mut v = Vec::new();
        encode_name(&mut v, "a.bc.local");
        let (n, p) = read_name(&v, 0).unwrap();
        assert_eq!(n, "a.bc.local");
        assert_eq!(p, v.len());
    }

    #[test]
    fn parses_ptr_srv_a() {
        // Build a fake response: PTR -> "Dev._netaudio-arc._udp.local",
        // SRV -> dev.local, A dev.local -> 10.0.0.5
        let mut p = vec![0u8, 0, 0x84, 0, 0, 0, 0, 3, 0, 0, 0, 0];
        encode_name(&mut p, SERVICE);
        p.extend_from_slice(&[0, 12, 0, 1, 0, 0, 0, 10]);
        let mut rd = Vec::new();
        encode_name(&mut rd, "Dev._netaudio-arc._udp.local");
        p.extend_from_slice(&(rd.len() as u16).to_be_bytes());
        p.extend_from_slice(&rd);
        encode_name(&mut p, "Dev._netaudio-arc._udp.local");
        p.extend_from_slice(&[0, 33, 0, 1, 0, 0, 0, 10]);
        let mut rd = vec![0, 0, 0, 0, 0x11, 0x5c];
        encode_name(&mut rd, "dev.local");
        p.extend_from_slice(&(rd.len() as u16).to_be_bytes());
        p.extend_from_slice(&rd);
        encode_name(&mut p, "dev.local");
        p.extend_from_slice(&[0, 1, 0, 1, 0, 0, 0, 10, 0, 4, 10, 0, 0, 5]);
        let devs = parse_answers(&p, Ipv4Addr::new(1, 1, 1, 1));
        assert_eq!(devs.len(), 1);
        assert_eq!(devs[0].name, "Dev");
        assert_eq!(devs[0].host, "dev");
        assert_eq!(devs[0].ip, "10.0.0.5");
    }
}
