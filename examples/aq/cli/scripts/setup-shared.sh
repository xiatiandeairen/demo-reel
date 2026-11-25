#!/bin/bash
# The "without aq" scene: one simulator of the demo's own (sim-boot.sh, no aq lease), shared by every agent.
exec bash "$(dirname "$0")/setup-sims.sh" "$1" shared
