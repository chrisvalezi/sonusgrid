#!/usr/bin/env bash
# changelog-section.sh X.Y.Z — print the "## [X.Y.Z]" section of CHANGELOG.md
set -euo pipefail
V="${1:?version}"
awk -v v="$V" '
  /^## \[/ { if (found) exit; if (index($0, "## [" v "]") == 1) { found = 1; next } }
  found { print }
' "$(dirname "${BASH_SOURCE[0]}")/../CHANGELOG.md"
