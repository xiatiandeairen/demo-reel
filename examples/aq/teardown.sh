#!/bin/bash
# Returns the simulators the demo borrowed, from the demo's own aq ledger in $1, and stops its page server.
demo=${1:-/tmp/aq-demo}
[[ -f $demo/server.pid ]] && kill "$(cat "$demo/server.pid")" 2>/dev/null
[[ -f $demo/env ]] || exit 0
source "$demo/env"
aq status 2>/dev/null | jq -r 'select(.status == "held") | .id' | while read -r id; do aq release "$id" >/dev/null; done
exit 0
