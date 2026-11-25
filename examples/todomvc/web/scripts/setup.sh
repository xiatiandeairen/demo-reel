#!/bin/bash
# The agent runs this before reel make: fetches only the built vanilla-JS TodoMVC app
# (tastejs/todomvc, examples/javascript-es6/dist) into $1 and serves it on 127.0.0.1:8765.
# Stop the server afterwards with: kill "$(cat "$1/server.pid")"
set -euo pipefail
work=${1:-/tmp/reel-todomvc}
rm -rf "$work" && mkdir -p "$work"
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/tastejs/todomvc "$work/todomvc"
git -C "$work/todomvc" sparse-checkout set examples/javascript-es6/dist
/usr/bin/python3 -m http.server 8765 --bind 127.0.0.1 --directory "$work/todomvc/examples/javascript-es6/dist" \
  >/dev/null 2>&1 & echo $! > "$work/server.pid"
until curl -s -o /dev/null http://127.0.0.1:8765/; do sleep 0.2; done
echo "serving http://127.0.0.1:8765/"
