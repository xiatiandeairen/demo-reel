#!/bin/bash
# Scene 2 setup: one simulator borrowed before recording, shared by every agent.
exec bash "$(dirname "$0")/setup-sims.sh" "$1" shared
