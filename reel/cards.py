"""Title cards and captions as PNGs, drawn by headless Chrome from HTML.

The composer overlays these images on the video (this ffmpeg build may lack drawtext).
"""
from __future__ import annotations

import html
import subprocess
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

FONT = "-apple-system, 'SF Pro Display', 'Helvetica Neue', Inter, sans-serif"


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise RuntimeError("needs Google Chrome or Chromium in /Applications to draw cards")


def _shot(page: str, out: Path, w: int, h: int):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "card.html"
        src.write_text(page)
        subprocess.run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--window-size={w},{h}",
                        "--default-background-color=00000000", f"--user-data-dir={tmp}/profile",
                        f"--screenshot={out}", src.as_uri()],
                       check=True, capture_output=True, timeout=60)


def title_card(out: Path, title: str, subtitle: str, accent: list, w=1920, h=1080):
    c0, c1 = accent[:2]
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden}}
body{{background:linear-gradient(135deg,{c0},{c1});display:flex;flex-direction:column;
align-items:center;justify-content:center;font-family:{FONT};color:#fff}}
h1{{font-size:{int(h * 0.12)}px;font-weight:700;letter-spacing:-0.02em;margin:0}}
p{{font-size:{int(h * 0.036)}px;font-weight:500;opacity:.85;margin:{int(h * 0.02)}px 0 0;max-width:80%;text-align:center}}
</style><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p>"""
    _shot(page, out, w, h)


def _keycaps(keys) -> str:
    if not keys:
        return ""
    keys = [keys] if isinstance(keys, str) else list(keys)
    caps = "".join(f'<kbd>{html.escape(k)}</kbd>' for k in keys)
    return f'<span class="keys">{caps}</span>'


def caption(out: Path, text: str, keys=None, w=1920, h=1080):
    """A full-frame transparent PNG: one narration sentence near the bottom, with optional keycaps.

    Sentences wrap to at most two lines; keys (e.g. "space" or ["cmd", "k"]) follow as keycaps,
    like lazygit's "Stage a file  Pressing <space>".
    """
    fs = int(h * 0.034)
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent}}
.c{{position:absolute;left:50%;bottom:{int(h * 0.055)}px;transform:translateX(-50%);
max-width:{int(w * 0.72)}px;width:max-content;padding:{int(h * 0.013)}px {int(h * 0.024)}px;
border-radius:{int(h * 0.022)}px;background:rgba(12,13,18,.78);backdrop-filter:blur(8px);
color:#fff;font-family:{FONT};font-size:{fs}px;font-weight:600;line-height:1.3;text-align:center;
box-shadow:0 10px 34px rgba(0,0,0,.35);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
.keys{{display:inline-flex;gap:{int(fs * 0.25)}px;margin-left:{int(fs * 0.45)}px;vertical-align:{int(fs * 0.08)}px}}
kbd{{font-family:{FONT};font-size:{int(fs * 0.72)}px;font-weight:600;color:#0c0d12;background:linear-gradient(#fff,#d9dbe3);
border-radius:{int(fs * 0.22)}px;padding:{int(fs * 0.06)}px {int(fs * 0.3)}px;box-shadow:0 {int(fs * 0.08)}px 0 #8b8f9c}}
</style><div class="c">{html.escape(text)}{_keycaps(keys)}</div>"""
    _shot(page, out, w, h)


def backdrop(accent: list, w: int) -> tuple:
    """(css, markup) for a wallpaper-like backdrop: soft colour fields in the accent colours over
    a dark base, with fine grain. Shared by terminal backgrounds and the stage underlay."""
    c0, c1 = accent[:2]
    css = f"""body{{background:#0b0d14}}
.bd{{position:absolute;inset:-20%;filter:blur({int(w * 0.04)}px);background:
radial-gradient(40% 50% at 18% 22%, {c1} 0%, transparent 70%),
radial-gradient(45% 55% at 85% 30%, {c0} 0%, transparent 72%),
radial-gradient(55% 60% at 60% 95%, {c1}cc 0%, transparent 70%),
radial-gradient(35% 40% at 30% 80%, {c0}aa 0%, transparent 70%);opacity:.95}}
.grain{{position:absolute;inset:0;width:100%;height:100%;opacity:.10;mix-blend-mode:overlay}}"""
    markup = ('<div class="bd"></div><svg class="grain" xmlns="http://www.w3.org/2000/svg"><filter id="n">'
              '<feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/></filter>'
              '<rect width="100%" height="100%" filter="url(#n)"/></svg>')
    return css, markup


def background(out: Path, accent: list, w: int, h: int):
    css, markup = backdrop(accent, w)
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;position:relative}}
{css}</style>{markup}"""
    _shot(page, out, w, h)


def stat_card(out: Path, lines: list, accent: list, w=1920, h=1080):
    """A results card: one large line per figure over the backdrop, e.g. "Builds run: 3 → 1"."""
    css, markup = backdrop(accent, w)
    rows = "".join(f"<p>{html.escape(t)}</p>" for t in lines)
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;position:relative}}
{css}
.s{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
font-family:{FONT};color:#fff;font-variant-numeric:tabular-nums}}
.s p{{font-size:{int(h * 0.075)}px;font-weight:700;letter-spacing:-0.01em;margin:{int(h * 0.018)}px 0;
text-shadow:0 6px 30px rgba(0,0,0,.35)}}
</style>{markup}<div class="s">{rows}</div>"""
    _shot(page, out, w, h)


def device_frames(out: Path, labels: list, rects: list, w: int, h: int):
    """A transparent stage-sized PNG: a phone body around each screen rect, a dark screen until the
    device's recording starts, and its label underneath."""
    parts = []
    for label, (x0, y0, x1, y1) in zip(labels, rects):
        sw, sh = x1 - x0, y1 - y0
        b = round(sw * 0.035)
        parts.append(f'<div class="ph" style="left:{x0 - b}px;top:{y0 - b}px;width:{sw}px;height:{sh}px;'
                     f'border-width:{b}px;border-radius:{round(sw * 0.12) + b}px"></div>'
                     f'<div class="lb" style="left:{x0}px;top:{y1 + b + 24}px;width:{sw}px">{html.escape(label)}</div>')
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent;position:relative}}
.ph{{position:absolute;border-style:solid;border-color:#2a2e3a;background:#1a1d27;box-shadow:0 30px 90px rgba(0,0,0,.45)}}
.lb{{position:absolute;text-align:center;font-family:{FONT};font-size:{int(h * 0.026)}px;font-weight:600;color:#e8eaf2}}
</style>{"".join(parts)}"""
    _shot(page, out, w, h)


def rounded_mask(out: Path, w: int, h: int, r: int):
    """White rounded rectangle on black: the alpha mask that rounds a phone screen's corners."""
    page = f"""<!doctype html><style>html,body{{margin:0;width:{w}px;height:{h}px;background:#000;overflow:hidden}}
div{{width:{w}px;height:{h}px;border-radius:{r}px;background:#fff}}</style><div></div>"""
    _shot(page, out, w, h)
