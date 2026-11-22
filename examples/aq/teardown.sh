#!/bin/bash
# Returns the simulators the demo borrowed, from the demo's own aq ledger in $1.
demo=${1:-/tmp/aq-demo}
[[ -f $demo/env ]] || exit 0
source "$demo/env"
aq status 2>/dev/null | jq -r 'select(.status == "held") | .id' | while read -r id; do aq release "$id" >/dev/null; done
