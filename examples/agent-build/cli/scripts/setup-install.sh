#!/bin/bash
# Install scene: cargo installs into <workdir>/cargo, used as both CARGO_HOME and the install root, so your
# own cargo (its bin and its git cache) is untouched; records your agb's state to compare afterwards.
# rustup's cargo proxy does not pass a CARGO_HOME set here on to cargo, so the toolchain's own cargo
# binary goes first on PATH (same version; found with `rustup which cargo`).
set -euo pipefail
demo=${1:?workdir}
rm -rf "$demo" && mkdir -p "$demo/cargo"  # a reset: each rehearsal and take starts from nothing
real=$(rustup which cargo 2>/dev/null || command -v cargo)
cat > "$demo/env" <<ENV
export PATH=$(dirname "$real"):\$PATH CARGO_HOME=$demo/cargo CARGO_INSTALL_ROOT=$demo/cargo
ENV
mine=${CARGO_HOME:-$HOME/.cargo}/bin/agb
stat -f '%m %z' "$mine" > "$demo/agb-before.txt" 2>/dev/null || echo none > "$demo/agb-before.txt"
