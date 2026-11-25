#!/bin/bash
# Setup for the scenes with simulators: the usual demo (setup.sh), plus pages that say "Agent A" /
# "Agent B" served on localhost (simulators reach the Mac's localhost), and `sim-open <A|B>`, which
# opens that agent's page on its simulator.
#   bash setup-sims.sh <workdir> shared   one simulator of the demo's own (sim-boot.sh), which every agent
#                                         uses ($demo/sim): no aq lease, so nothing stays borrowed after the take
#   bash setup-sims.sh <workdir> own      agents borrow their own on screen (aq hold ios-sim):
#                                         agent A gets the first simulator held, B the second
set -euo pipefail
demo=${1:-/tmp/aq-demo}
mode=${2:-own}
here=$(cd "$(dirname "$0")" && pwd)
bash "$here/setup.sh" "$demo" >/dev/null
source "$demo/env"
port=$((47000 + RANDOM % 1000))
mkdir -p "$demo/www" "$demo/bin"
# Dark slate, like reel's empty phone, yet far enough from black that a launching Safari's black
# screen is not taken for it.
echo '<html><body style="margin:0;background:#1a1d27"></body></html>' > "$demo/www/blank.html"
for n in A B; do
  c=$([[ $n == A ]] && echo '#1596b8' || echo '#e0a030')
  cat > "$demo/www/$n.html" <<HTML
<html><meta name=viewport content="width=device-width"><body style="margin:0;height:100vh;display:flex;
align-items:center;justify-content:center;background:$c;font:bold 22vw -apple-system;color:white">Agent $n</body></html>
HTML
done
# The system python: a pyenv shim hangs when started in the background like this.
nohup /usr/bin/python3 -m http.server "$port" -d "$demo/www" >/dev/null 2>"$demo/server.log" &
echo $! > "$demo/server.pid"
for _ in $(seq 50); do curl -sf "http://localhost:$port/A.html" >/dev/null && break; sleep 0.1; done
curl -sf "http://localhost:$port/A.html" >/dev/null || { echo "page server did not start" >&2; exit 1; }
cat > "$demo/bin/sim-show" <<'SH'
#!/bin/bash
# sim-show <simulator> <url> <r> <g> <b>: opens url and returns once the screen shows that colour
# (sampled above the middle), so a busy machine's slow page load is waited out. Fails after about 30 s.
sim=$1 url=$2; shift 2
xcrun simctl openurl "$sim" "$url"
png=$(mktemp -t simshow).png
for i in $(seq 40); do
  # A fresh Safari can take the request yet stay on its start page: ask again every few seconds.
  (( i % 4 == 0 )) && xcrun simctl openurl "$sim" "$url"
  xcrun simctl io "$sim" screenshot "$png" >/dev/null 2>&1
  read -r r g b < <(ffmpeg -loglevel error -i "$png" -vf "crop=iw/4:ih/10:iw*3/8:ih/4,scale=1:1:flags=area,format=rgb24" -f rawvideo - | od -An -tu1)
  d=$(( (r>$1 ? r-$1 : $1-r) + (g>$2 ? g-$2 : $2-g) + (b>$3 ? b-$3 : $3-b) ))
  (( d <= 40 )) && { rm -f "$png"; exit 0; }
  sleep 0.3
done
rm -f "$png"; echo "the page did not show: $url" >&2; exit 1
SH
cat > "$demo/bin/sim-open" <<SH
#!/bin/bash
# sim-open <A|B>: shows agent <A|B>'s page on its simulator, and returns once it is on screen.
n=\${1:?A or B}
if [[ -f $demo/sim ]]; then sim=\$(cat $demo/sim)
else sim=\$(aq status | jq -r 'select(.status == "held") | .devices[0].id' | sed -n "\$([[ \$n == A ]] && echo 1 || echo 2)p"); fi
[[ -n \$sim ]] || { echo "no simulator for agent \$n" >&2; exit 1; }
if [[ ! -f $demo/sim ]]; then  # a borrowed one: wait until sim-find has Safari ready on it
  for _ in \$(seq 900); do [[ -f $demo/ready-\$sim ]] && break; sleep 0.1; done
fi
if [[ \$n == A ]]; then rgb="21 150 184"; else rgb="224 160 48"; fi
sim-show "\$sim" "http://localhost:$port/\$n.html?\$RANDOM" \$rgb && echo "Agent \$n's page is up"
SH
cat > "$demo/bin/sim-find" <<SH
#!/bin/bash
# sim-find <k>: the k-th simulator held through aq (prints nothing until there is one). The first
# time, it first brings Safari up on a dark blank page and only then prints the UDID: a fresh
# Safari's first launch takes 10-15 s while recording, and the phone (still a dark placeholder,
# since its recording starts when this prints) and the terminal stay still meanwhile, so the film
# cuts that wait.
udid=\$(aq status | jq -r 'select(.status == "held") | .devices[0].id' | sed -n "\${1}p")
[[ -n \$udid ]] || exit 0
if [[ ! -f $demo/ready-\$udid ]]; then
  sim-show "\$udid" "http://localhost:$port/blank.html" 26 29 39 >/dev/null 2>&1 || exit 0
  touch $demo/ready-\$udid
fi
echo "\$udid"
SH
chmod +x "$demo/bin/sim-open" "$demo/bin/sim-show" "$demo/bin/sim-find"
echo "export PATH=$demo/bin:\$PATH" >> "$demo/env"
if [[ $mode == shared ]]; then
  sim=$(bash "$here/sim-boot.sh" "demo-reel aq shared")
  [[ $sim =~ ^[0-9A-F-]{36}$ ]] || { echo "could not boot the demo's simulator: $sim" >&2; exit 1; }
  echo "$sim" > "$demo/sim"
  # Safari's first launch is slow and opens its start page: show a page once, then a dark blank one.
  "$demo/bin/sim-show" "$sim" "http://localhost:$port/A.html" 21 150 184
  "$demo/bin/sim-show" "$sim" "http://localhost:$port/blank.html" 26 29 39
fi
