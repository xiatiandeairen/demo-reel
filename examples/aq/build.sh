#!/bin/bash
# Stand-in for a heavy build: keeps 4 CPU cores busy for about 8 seconds.
echo "Compiling App (4 cores)…"
for _ in 1 2 3 4; do (end=$((SECONDS + 8)); while ((SECONDS < end)); do :; done) & done
wait
echo "Build succeeded"
