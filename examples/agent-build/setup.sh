#!/bin/bash
# Prepares an isolated agent-build demo in $1: the sample app from agent-build's tests/fixtures in a git
# repo "app" with two more worktrees, "app-feature" and "app-fix", agb's own cache and config under $1,
# and agb first on PATH. Your real build slots are not touched.
#   bash setup.sh <workdir> fresh     nothing built yet (the GIF: a cold first build, then a new worktree)
#   bash setup.sh <workdir> xcode     "app" already built with plain xcodebuild (the without-agb scene)
#   bash setup.sh <workdir> agb       "app" already built with agb, so its slot is warm (the with-agb scene)
# Needs AGB_REPO (an agent-build checkout, for the sample app); agb is taken from $AGB_BIN_DIR if set,
# else from PATH. To record this checkout's agb: (cd "$AGB_REPO" && cargo build --release) and set
# AGB_BIN_DIR="$AGB_REPO/target/release".
set -euo pipefail
demo=${1:?workdir}
mode=${2:-fresh}
repo=${AGB_REPO:?set AGB_REPO to an agent-build checkout}
rm -rf "$demo" && mkdir -p "$demo"
cp -R "$repo/tests/fixtures/SampleApp" "$demo/app"
cd "$demo/app"
git init -q && git add -A
git -c core.hooksPath=/dev/null -c user.name=demo -c user.email=demo@example.com commit -qm "chore: init"
git worktree add -q ../app-feature -b feature
git worktree add -q ../app-fix -b fix
cat > "$demo/env" <<ENV
export PATH=${AGB_BIN_DIR:+$AGB_BIN_DIR:}\$PATH BASH_SILENCE_DEPRECATION_WARNING=1
export XDG_CACHE_HOME=$demo/cache XDG_CONFIG_HOME=$demo/config
ENV
source "$demo/env"
command -v agb >/dev/null || { echo "agb is not on PATH; set AGB_BIN_DIR" >&2; exit 1; }
dest='generic/platform=iOS Simulator'
case $mode in
  xcode) xcodebuild build -scheme App -destination "$dest" -derivedDataPath ../dd-app >/dev/null 2>&1 ;;
  agb) agb xcodebuild build -scheme App -destination "$dest" >/dev/null 2>&1 ;;
esac
