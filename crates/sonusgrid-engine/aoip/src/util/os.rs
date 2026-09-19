use thread_priority::{thread_native_id, Error};

#[cfg(target_family = "unix")]
pub fn set_current_thread_realtime(priority_hint: u8) -> Result<(), Error> {
  use thread_priority::unix::set_thread_priority_and_policy;
  use thread_priority::{
    RealtimeThreadSchedulePolicy, ThreadPriority, ThreadPriorityValue, ThreadSchedulePolicy,
  };

  let direct = set_thread_priority_and_policy(
    thread_native_id(),
    ThreadPriority::Crossplatform(ThreadPriorityValue::try_from(priority_hint).unwrap()),
    ThreadSchedulePolicy::Realtime(RealtimeThreadSchedulePolicy::Fifo),
  );
  if direct.is_ok() {
    log::info!("realtime scheduling: SCHED_FIFO {priority_hint}");
    return direct;
  }
  // SonusGrid: RLIMIT_RTPRIO is usually 0 inside a `systemd --user` session,
  // so fall back to rtkit (the desktop-standard path PipeWire uses). rtkit
  // caps the priority (20 by default) and requires an RTTIME watchdog.
  #[cfg(target_os = "linux")]
  {
    let rl = libc::rlimit { rlim_cur: 200_000, rlim_max: 200_000 };
    unsafe { libc::setrlimit(libc::RLIMIT_RTTIME, &rl) };
    let pid = std::process::id();
    let tid = unsafe { libc::syscall(libc::SYS_gettid) } as u64;
    let prio = 20u32.min(priority_hint as u32);
    let out = std::process::Command::new("busctl")
      .args([
        "--system", "--timeout=3", "call",
        "org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1",
        "org.freedesktop.RealtimeKit1", "MakeThreadRealtimeWithPID", "ttu",
        &pid.to_string(), &tid.to_string(), &prio.to_string(),
      ])
      .output();
    match out {
      Ok(o) if o.status.success() => {
        log::info!("realtime scheduling: SCHED_FIFO {prio} via rtkit (rlimit refused {priority_hint})");
        return Ok(());
      }
      Ok(o) => log::warn!(
        "no realtime scheduling for this thread (rlimit: {:?}; rtkit: {}) — audio may drop out under CPU load",
        direct, String::from_utf8_lossy(&o.stderr).trim()
      ),
      Err(e) => log::warn!("no realtime scheduling for this thread (rlimit: {:?}; busctl: {e})", direct),
    }
  }
  direct
}

#[cfg(not(target_family = "unix"))]
pub fn set_current_thread_realtime(_priority_hint: u32) -> Result<(), Error> {
  thread_priority::set_current_thread_priority(ThreadPriority::Max)
}
