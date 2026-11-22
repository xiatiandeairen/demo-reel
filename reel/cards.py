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


def caption(out: Path, text: str, w=1920, h=1080):
    """A full-frame transparent PNG with a caption pill near the bottom."""
    page = f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent}}
div{{position:absolute;left:50%;bottom:{int(h * 0.06)}px;transform:translateX(-50%);
max-width:{int(w * 0.8)}px;padding:{int(h * 0.014)}px {int(h * 0.026)}px;border-radius:{int(h * 0.03)}px;
background:rgba(15,17,26,.82);color:#fff;font-family:{FONT};font-size:{int(h * 0.032)}px;font-weight:600;
box-shadow:0 8px 30px rgba(0,0,0,.35);white-space:nowrap}}
</style><div>{html.escape(text)}</div>"""
    _shot(page, out, w, h)
