#!/usr/bin/env bash
# Wrapper that puts the bundled sonus_gtk package on PYTHONPATH and launches it.
# Installed as /usr/bin/sonusgrid-gtk by the .deb. To run from a source
# checkout: SONUSGRID_GUI_DIR=/path/to/repo/gui/sonus-gtk sonusgrid-gtk
SONUSGRID_GUI_DIR="${SONUSGRID_GUI_DIR:-/usr/share/sonusgrid/gui}"
export PYTHONPATH="${SONUSGRID_GUI_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m sonus_gtk "$@"
