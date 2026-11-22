#!/bin/bash
# Fetches only the built vanilla-JS TodoMVC app (tastejs/todomvc, examples/javascript-es6/dist) into $1.
set -euo pipefail
work=${1:?workdir}
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/tastejs/todomvc "$work/todomvc"
git -C "$work/todomvc" sparse-checkout set examples/javascript-es6/dist
