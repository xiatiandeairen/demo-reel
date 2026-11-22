#!/bin/bash
# Stand-in for a heavy build: keeps 4 CPU cores busy for about 14 seconds (long enough for the narrated steps before it finishes).
# Each real run appends "<start> <end>" (epoch seconds) to $REEL_WORK/runs.log; the film's results card counts them.
start=$(date +%s)
echo "Compiling App (4 cores)…"
# Low CPU priority (nice), so a simulator on screen stays responsive while three of these run.
for _ in 1 2 3 4; do nice -n 15 bash -c 'end=$((SECONDS + 14)); while ((SECONDS < end)); do :; done' & done
wait
echo "$start $(date +%s)" >> "${REEL_WORK:-.}/runs.log"
echo "Build succeeded"
