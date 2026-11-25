#!/bin/bash
# Gives the hello scene an empty working folder before each rehearsal and take.
set -euo pipefail
rm -rf "$REEL_WORK" && mkdir -p "$REEL_WORK"
