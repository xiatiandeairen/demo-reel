#!/bin/bash
# Fails the recording if your own agb (in your CARGO_HOME, default ~/.cargo) changed during the install scene.
demo=${1:?workdir}
mine=${CARGO_HOME:-$HOME/.cargo}/bin/agb
now=$(stat -f '%m %z' "$mine" 2>/dev/null || echo none)
[[ $now == "$(cat "$demo/agb-before.txt")" ]] || { echo "$mine changed during the install scene" >&2; exit 1; }
