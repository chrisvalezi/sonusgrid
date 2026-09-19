# SPDX-License-Identifier: GPL-3.0-or-later
"""Launching external tools, install hints, DAW launcher creation, docs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from gi.repository import Gio, GLib

TOOL_PACKAGES = {
    "qpwgraph": {"apt": "qpwgraph", "dnf": "qpwgraph", "pacman": "qpwgraph", "zypper": "qpwgraph"},
    "pavucontrol": {"apt": "pavucontrol", "dnf": "pavucontrol", "pacman": "pavucontrol", "zypper": "pavucontrol"},
    "pw-jack": {"apt": "pipewire-jack", "dnf": "pipewire-jack-audio-connection-kit", "pacman": "pipewire-jack", "zypper": "pipewire-jack"},
}


def detect_package_manager() -> str | None:
    ids: list[str] = []
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if k == "ID":
                    ids.append(v)
                elif k == "ID_LIKE":
                    ids.extend(v.split())
    except Exception:
        pass
    for ident in ids:
        if ident in ("debian", "ubuntu", "linuxmint", "pop", "elementary", "kali", "raspbian", "zorin"):
            return "apt"
        if ident in ("fedora", "rhel", "centos", "rocky", "alma"):
            return "dnf"
        if ident in ("arch", "manjaro", "endeavouros", "garuda"):
            return "pacman"
        if ident.startswith("opensuse") or ident in ("suse", "sles"):
            return "zypper"
    for pm in ("apt", "dnf", "pacman", "zypper"):
        if shutil.which(pm):
            return pm
    return None


def install_command(tool: str) -> str | None:
    pm = detect_package_manager()
    pkg = TOOL_PACKAGES.get(tool, {}).get(pm or "")
    if not pm or not pkg:
        return None
    return {
        "apt": f"sudo apt update && sudo apt install -y {pkg}",
        "dnf": f"sudo dnf install -y {pkg}",
        "pacman": f"sudo pacman -S --needed {pkg}",
        "zypper": f"sudo zypper install -y {pkg}",
    }[pm]


def is_installed(tool: str) -> bool:
    return shutil.which(tool) is not None


def launch(argv: list[str]) -> bool:
    """Detached launch. Returns False if the binary is missing."""
    if not shutil.which(argv[0]):
        return False
    try:
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        return True
    except GLib.Error:
        return False


def open_uri(path_or_uri: str) -> None:
    uri = path_or_uri if "://" in path_or_uri else Gio.File.new_for_path(path_or_uri).get_uri()
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        launch(["xdg-open", path_or_uri])


def find_doc(name: str) -> Path | None:
    """Locate a shipped doc (installed) or a source-tree doc."""
    here = Path(__file__).resolve()
    candidates = [
        Path("/usr/share/doc/sonusgrid") / name,
        Path("/usr/share/doc/sonusgrid") / (name + ".gz"),
        Path("/usr/local/share/doc/sonusgrid") / name,
        here.parents[3] / "docs" / name,        # <repo>/docs
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


DAWS = [
    ("reaper", "REAPER", "reaper", "application/x-reaper-project"),
    ("ardour", "Ardour", "ardour", "application/x-ardour"),
    ("ardour8", "Ardour 8", "ardour", "application/x-ardour"),
    ("ardour7", "Ardour 7", "ardour", "application/x-ardour"),
    ("bitwig-studio", "Bitwig Studio", "bitwig-studio", ""),
    ("mixbus", "Mixbus", "mixbus", "application/x-ardour"),
    ("mixbus32c", "Mixbus 32C", "mixbus", "application/x-ardour"),
    ("muse", "MusE", "muse", ""),
    ("qtractor", "Qtractor", "qtractor", ""),
    ("renoise", "Renoise", "renoise", ""),
]


def installed_daws() -> list[tuple[str, str]]:
    return [(b, n) for b, n, _i, _m in DAWS if shutil.which(b)]


def create_daw_launchers() -> tuple[list[str], str]:
    """Write ~/.local/share/applications/<daw>-jack.desktop for each DAW found.
    Returns (created_names, error)."""
    if not shutil.which("pw-jack"):
        return [], "pw-jack"
    out_dir = Path(GLib.get_user_data_dir()) / "applications"
    out_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for binary, name, icon, mime in DAWS:
        if not shutil.which(binary):
            continue
        content = (
            "[Desktop Entry]\nType=Application\n"
            f"Name={name} (JACK / SonusGrid)\nGenericName=Digital Audio Workstation\n"
            f"Comment={name} bound to PipeWire-JACK for SonusGrid Dante I/O\n"
            f"Exec=pw-jack {binary} %F\nIcon={icon}\nTerminal=false\n"
            "Categories=AudioVideo;Audio;Music;\n"
            + (f"MimeType={mime};\n" if mime else "")
            + "StartupNotify=true\nKeywords=DAW;Audio;Recording;Music;JACK;\n"
        )
        try:
            (out_dir / f"{binary}-jack.desktop").write_text(content)
            created.append(name)
        except Exception:
            pass
    try:
        subprocess.run(["update-desktop-database", str(out_dir)], capture_output=True, timeout=5)
    except Exception:
        pass
    return created, ""
