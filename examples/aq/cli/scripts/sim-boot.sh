#!/bin/bash
# sim-boot.sh <name>: prints the UDID of the demo's own simulator called <name>, booted. Creates it the
# first time (an iPhone 17 Pro on the newest iOS runtime installed); later runs reuse it. Plain simctl,
# no aq: the shared simulator of the "without aq" scene must not hold one of aq's leases.
set -euo pipefail
name=${1:?simulator name}
udid=$(xcrun simctl list devices -j | jq -r --arg n "$name" '[.devices[][] | select(.name == $n and .isAvailable)][0].udid // empty')
if [[ -z $udid ]]; then
  runtime=$(xcrun simctl list runtimes -j | jq -r '[.runtimes[] | select(.platform == "iOS" and .isAvailable)] | last | .identifier')
  udid=$(xcrun simctl create "$name" com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro "$runtime")
fi
xcrun simctl bootstatus "$udid" -b >/dev/null
echo "$udid"
