#!/bin/bash
# Returns the simulators the demo borrowed, from the demo's own aq ledger in $1, stops its page server,
# and shuts the demo's own shared simulator down: aq lends no more simulators while too many are booted
# (2026-11-25: the third booted one left "aq hold ios-sim" waiting).
demo=${1:-/tmp/aq-demo}
xcrun simctl shutdown "demo-reel aq shared" 2>/dev/null
[[ -f $demo/server.pid ]] && kill "$(cat "$demo/server.pid")" 2>/dev/null
[[ -f $demo/env ]] || exit 0
source "$demo/env"
aq status 2>/dev/null | jq -r 'select(.status == "held") | .id' | while read -r id; do aq release "$id" >/dev/null; done
exit 0
