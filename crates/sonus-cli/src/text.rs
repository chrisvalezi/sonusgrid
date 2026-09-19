// SPDX-License-Identifier: GPL-3.0-or-later
//! Tiny bilingual message helper. We deliberately keep this in-tree and small
//! instead of pulling in gettext for the CLI: every user-visible string is here,
//! easy to audit and easy for translators to extend.

#[derive(Copy, Clone, Eq, PartialEq, Debug)]
pub enum Lang {
    Pt,
    En,
}

pub fn resolve_lang(forced: Option<&str>) -> Lang {
    if let Some(s) = forced {
        return match s {
            "pt" => Lang::Pt,
            "en" => Lang::En,
            _ => detect_from_env(),
        };
    }
    detect_from_env()
}

fn detect_from_env() -> Lang {
    let val = std::env::var("LC_ALL")
        .or_else(|_| std::env::var("LC_MESSAGES"))
        .or_else(|_| std::env::var("LANG"))
        .unwrap_or_default();
    if val.starts_with("pt") {
        Lang::Pt
    } else {
        Lang::En
    }
}

/// Pick a string by language. Pattern: `t(lang, "PT version", "EN version")`.
#[allow(dead_code)] // used by future GUI-shared messages
pub fn t<'a>(lang: Lang, pt: &'a str, en: &'a str) -> &'a str {
    match lang {
        Lang::Pt => pt,
        Lang::En => en,
    }
}

/// Print PT and EN side by side. Use for diagnostics/output that may end up
/// in forum posts or support tickets.
pub fn dual_println(pt: &str, en: &str) {
    println!("[PT] {pt}");
    println!("[EN] {en}");
}
