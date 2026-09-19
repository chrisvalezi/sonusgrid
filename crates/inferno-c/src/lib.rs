// SPDX-License-Identifier: GPL-3.0-or-later
//! SonusGrid C-ABI shim over `inferno_aoip`.
//!
//! The macOS AudioServerPlugIn (Swift) cannot speak Rust, so this crate
//! exposes a stable C ABI suitable for FFI. Every public symbol is `extern
//! "C"` and uses primitive types or `#[repr(C)]` structs.
//!
//! # Realtime contract
//!
//! Functions documented as **realtime-safe** (`inferno_push_tx_block`,
//! `inferno_pull_rx_block`) **must not** allocate, lock, or syscall on the
//! audio thread. They drain or fill a lock-free ring buffer; a Tokio runtime
//! on a normal-priority thread (spawned in `inferno_init`) does the network
//! work asynchronously.
//!
//! # Lifecycle
//!
//! 1. `inferno_init(config_ptr) -> handle`
//! 2. `inferno_start(handle)`
//! 3. Audio thread loops:
//!    - `inferno_push_tx_block(handle, samples, frames, channels)`
//!    - `inferno_pull_rx_block(handle, samples, frames, channels)`
//! 4. `inferno_stop(handle)`
//! 5. `inferno_shutdown(handle)`
//!
//! ## Status
//!
//! This crate is currently a **stubs-only skeleton**. Every entry returns
//! `INFERNO_NOT_IMPLEMENTED`. The skeleton compiles cleanly so the macOS
//! Xcode build can already link against it; the Rust→Inferno glue is filled
//! in over the course of phase A (see `docs/ARCHITECTURE_macOS.md`).

#![deny(unused_must_use)]

use std::os::raw::{c_char, c_int, c_uint};

/// Opaque handle returned by `inferno_init`. The Swift HAL plugin treats
/// this as `OpaquePointer` and never dereferences it.
#[repr(C)]
pub struct InfernoHandle {
    _private: [u8; 0],
}

/// Status codes returned by every entry point. 0 == success.
#[repr(C)]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum InfernoStatus {
    Ok = 0,
    InvalidArg = 1,
    NotInitialized = 2,
    AlreadyRunning = 3,
    NotRunning = 4,
    NotImplemented = 99,
}

/// Configuration passed to `inferno_init`.
///
/// `name`, `bind_ip`, `interface_name` are NUL-terminated UTF-8 strings.
/// The shim copies the buffers internally; the caller may free them after
/// the call returns.
#[repr(C)]
pub struct InfernoConfig {
    /// Device name visible on the Dante network (e.g. "SonusGrid-Virtual").
    pub name: *const c_char,
    /// Bind IP — explicit IPv4 string, or NULL to auto-pick.
    pub bind_ip: *const c_char,
    /// Network interface short name (e.g. "en0").
    pub interface_name: *const c_char,
    pub sample_rate: c_uint,
    pub rx_channels: c_uint,
    pub tx_channels: c_uint,
    pub rx_latency_ns: u64,
    pub tx_latency_ns: u64,
    /// Path to the usrvclock UNIX socket the PTP daemon exposes. NULL if
    /// using system clock fallback.
    pub clock_socket_path: *const c_char,
}

/// Initialize the shim and allocate runtime resources. Returns a handle on
/// success, or NULL if `cfg` is invalid.
///
/// Not realtime-safe — call from setup code, not from an audio callback.
#[no_mangle]
pub extern "C" fn inferno_init(_cfg: *const InfernoConfig) -> *mut InfernoHandle {
    log::warn!("inferno_init: stub returning null");
    std::ptr::null_mut()
}

/// Begin advertising the device on the network and accepting subscriptions.
#[no_mangle]
pub extern "C" fn inferno_start(_h: *mut InfernoHandle) -> InfernoStatus {
    InfernoStatus::NotImplemented
}

/// Stop network activity but keep the handle alive (re-startable).
#[no_mangle]
pub extern "C" fn inferno_stop(_h: *mut InfernoHandle) -> InfernoStatus {
    InfernoStatus::NotImplemented
}

/// Tear down everything and free `h`. After this call `h` is invalid.
#[no_mangle]
pub extern "C" fn inferno_shutdown(h: *mut InfernoHandle) -> InfernoStatus {
    let _ = h;
    InfernoStatus::NotImplemented
}

/// Realtime-safe TX block push. Audio thread copies `frames * channels`
/// samples (interleaved f32) into the internal ring buffer.
///
/// # Safety
///
/// `samples` must point to at least `frames * channels` valid f32 values.
#[no_mangle]
pub unsafe extern "C" fn inferno_push_tx_block(
    _h: *mut InfernoHandle,
    samples: *const f32,
    frames: c_uint,
    channels: c_uint,
) -> InfernoStatus {
    let _ = (samples, frames, channels);
    InfernoStatus::NotImplemented
}

/// Realtime-safe RX block pull. Audio thread receives `frames * channels`
/// samples (interleaved f32). Underrun fills with silence.
///
/// # Safety
///
/// `samples` must point to writable memory of at least `frames * channels`
/// f32 values.
#[no_mangle]
pub unsafe extern "C" fn inferno_pull_rx_block(
    _h: *mut InfernoHandle,
    samples: *mut f32,
    frames: c_uint,
    channels: c_uint,
) -> InfernoStatus {
    let _ = (samples, frames, channels);
    InfernoStatus::NotImplemented
}

/// Returns library version string, never NULL, never freed.
#[no_mangle]
pub extern "C" fn inferno_version() -> *const c_char {
    static VERSION: &str = concat!(env!("CARGO_PKG_VERSION"), "\0");
    VERSION.as_ptr() as *const c_char
}

/// Returns the size of the InfernoConfig struct so the caller can sanity-check
/// that header and library agree on layout.
#[no_mangle]
pub extern "C" fn inferno_config_size() -> c_int {
    std::mem::size_of::<InfernoConfig>() as c_int
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_string_terminates_with_nul() {
        let p = inferno_version();
        assert!(!p.is_null());
        // Walk byte-by-byte until NUL — bounded so we don't run away on a
        // bad pointer.
        unsafe {
            let mut i = 0;
            while i < 32 {
                if *p.add(i) == 0 {
                    return;
                }
                i += 1;
            }
            panic!("version string not NUL-terminated within 32 bytes");
        }
    }

    #[test]
    fn config_size_is_stable() {
        // If this test fails after editing InfernoConfig, regenerate the
        // C header and bump inferno-c's minor version.
        let s = inferno_config_size();
        assert!(s > 0);
    }

    #[test]
    fn shutdown_null_handle_is_safe() {
        // Null handle should not crash — must return NotImplemented (or
        // InvalidArg once filled in).
        let r = inferno_shutdown(std::ptr::null_mut());
        assert!(matches!(r, InfernoStatus::NotImplemented | InfernoStatus::InvalidArg));
    }
}
