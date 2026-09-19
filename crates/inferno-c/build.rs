// SPDX-License-Identifier: GPL-3.0-or-later
//! Generate include/inferno.h on every build.

use std::env;
use std::path::PathBuf;

fn main() {
    let crate_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let out_path = crate_dir.join("include").join("inferno.h");

    let cfg = cbindgen::Config::from_file(crate_dir.join("cbindgen.toml")).unwrap_or_default();

    if let Ok(builder) = cbindgen::Builder::new()
        .with_config(cfg)
        .with_crate(crate_dir.clone())
        .generate()
    {
        builder.write_to_file(&out_path);
        println!(
            "cargo:warning=inferno-c: wrote {}",
            out_path.display()
        );
    } else {
        println!("cargo:warning=inferno-c: cbindgen skipped (no exported items yet)");
    }
}
