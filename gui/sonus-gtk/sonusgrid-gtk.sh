#!/usr/bin/env bash
# Wrapper that puts the bundled sonus_gtk package on PYTHONPATH and launches it.
# Installed as /usr/bin/sonusgrid-gtk by the .deb.
SONUSGRID_GUI_DIR="${SONUSGRID_GUI_DIR:-/usr/share/sonusgrid/gui}"
export PYTHONPATH="${SONUSGRID_GUI_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m sonus_gtk "$@"
