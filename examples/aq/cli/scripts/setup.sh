#!/bin/bash
# Prepares an isolated demo: its own aq ledger and config under $1 (default /tmp/aq-demo),
# with $AQ_BIN_DIR (if set) first on PATH so the demo uses that aq build,
# and a small git repo "app" with build.sh and test.sh, each run once so aq has measured them
# as heavy (about 4 cores). With heavy_slots = 1 the second heavy task then queues.
# Your real aq ledger is not touched.
set -euo pipefail
demo=${1:-/tmp/aq-demo}
here=$(cd "$(dirname "$0")" && pwd)
rm -rf "$demo" && mkdir -p "$demo/config/aq" "$demo/app"
cat > "$demo/config/aq/config.toml" <<'TOML'
heavy_slots = 1
disk_floor = "1G"
TOML
cat > "$demo/env" <<ENV
export PATH=${AQ_BIN_DIR:+$AQ_BIN_DIR:}\$PATH BASH_SILENCE_DEPRECATION_WARNING=1
export XDG_CONFIG_HOME=$demo/config XDG_STATE_HOME=$demo/state XDG_DATA_HOME=$demo/data XDG_CACHE_HOME=$demo/cache
ENV
cp "$here/build.sh" "$here/test.sh" "$demo/app/"
cd "$demo/app"
git init -q && git add -A && git -c core.hooksPath=/dev/null -c user.name=demo -c user.email=demo@example.com commit -qm "chore: init"
source "$demo/env"
for s in ./build.sh ./test.sh; do
  out=$(aq run --wait 60 -- "$s" 2>&1) || { echo "measuring $s with aq failed: $out" >&2; exit 1; }
done
: > "$demo/runs.log"  # the measuring runs above are not part of the demo
echo "demo ready: source $demo/env && cd $demo/app"
