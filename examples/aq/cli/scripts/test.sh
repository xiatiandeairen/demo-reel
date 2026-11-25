#!/bin/bash
# Stand-in for a heavy test run: keeps 4 CPU cores busy for about 6 seconds.
echo "Running 128 tests (4 cores)…"
for _ in 1 2 3 4; do (end=$((SECONDS + 6)); while ((SECONDS < end)); do :; done) & done
wait
echo "128 tests passed"
