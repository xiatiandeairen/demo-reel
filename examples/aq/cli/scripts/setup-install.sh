#!/bin/bash
# Setup for the install scene: a throwaway Claude Code config in <workdir>/claude, so installing the
# plugin on screen does not touch yours, and a copy of your plugin list to compare against afterwards.
set -euo pipefail
demo=${1:-/tmp/aq-demo-install}
rm -rf "$demo" && mkdir -p "$demo/claude"  # a reset: each rehearsal and take starts from nothing
claude plugin list > "$demo/plugins-before.txt" 2>&1
