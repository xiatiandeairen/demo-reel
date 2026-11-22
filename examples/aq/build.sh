#!/bin/bash
# Stand-in for a heavy build: keeps 4 CPU cores busy for about 14 seconds (long enough for the narrated steps before it finishes).
echo "Compiling App (4 cores)…"
for _ in 1 2 3 4; do (end=$((SECONDS + 14)); while ((SECONDS < end)); do :; done) & done
wait
echo "Build succeeded"
