#!/bin/bash
# Fails the recording if your own Claude Code plugin list changed (CASE-C4).
demo=${1:-/tmp/aq-demo-install}
claude plugin list > "$demo/plugins-after.txt" 2>&1
if ! cmp -s "$demo/plugins-before.txt" "$demo/plugins-after.txt"; then
  echo "your Claude Code plugin list changed during the install scene:" >&2
  diff "$demo/plugins-before.txt" "$demo/plugins-after.txt" >&2
  exit 1
fi
