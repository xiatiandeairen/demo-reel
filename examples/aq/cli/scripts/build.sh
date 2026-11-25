#!/bin/bash
# Stand-in for a heavy build: a fixed amount of work on 4 CPU cores, about 14 seconds on an idle Mac
# (long enough for the narrated steps before it finishes). Work, not a timer: builds that run at the
# same time slow each other down, as real ones do, and the results card measures that.
# Each real run appends "<start> <end>" (epoch seconds) to $REEL_WORK/runs.log; the film's results card counts them.
start=$(date +%s)
echo "Compiling App (4 cores)…"
# Low CPU priority (nice), so a simulator on screen stays responsive while three of these run.
for _ in 1 2 3 4; do nice -n 15 bash -c 'for ((i = 0; i < 9000000; i++)); do :; done' & done
wait
echo "$start $(date +%s)" >> "${REEL_WORK:-.}/runs.log"
echo "Build succeeded"
