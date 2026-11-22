"""Puts a raw screen recording (browser page, app window, simulator) on the shared stage.

The stage is what the terminal recorder gets from VHS: a 2880x1620 canvas with the accent gradient
and a framed window on it. Here the frame is drawn by headless Chrome (window bar for web pages,
a device bezel for iOS, just a shadow for Mac windows that bring their own title bar), and the
recording is laid into its hole with rounded corners.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import cards

W, H = 2880, 1620
FPS = 30


def _probe(path: Path) -> tuple:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "default=nw=1", str(path)],
                       capture_output=True, text=True, check=True)
    d = dict(l.split("=", 1) for l in r.stdout.split())
    return int(d["width"]), int(d["height"]), float(d["duration"])


def layout(kind: str, src_w: int, src_h: int) -> dict:
    """Where the recording goes on the stage: hole (x, y, w, h), corner radius, frame geometry."""
    if kind == "ios":
        bezel = 26
        h = H - 2 * 90 - 2 * bezel
        w = round(h * src_w / src_h)
        radius = round(w * 0.14)
    elif kind == "web":
        bezel = 0
        bar = 72
        max_w, max_h = W - 2 * 240, H - 2 * 80 - bar
        scale = min(max_w / src_w, max_h / src_h)
        w, h = round(src_w * scale), round(src_h * scale)
        radius = 20
    else:  # mac: the window has its own title bar
        bezel = 0
        max_w, max_h = W - 2 * 200, H - 2 * 100
        scale = min(max_w / src_w, max_h / src_h, 2.0)
        w, h = round(src_w * scale), round(src_h * scale)
        radius = 20
    bar = 72 if kind == "web" else 0
    x = (W - w) // 2
    y = (H - h + bar) // 2
    return {"kind": kind, "hole": [x, y, w, h], "radius": radius, "bezel": bezel, "bar": bar,
            "scale": w / src_w, "src": [src_w, src_h]}


def _underlay_html(lay: dict, accent: list, label: str) -> str:
    x, y, w, h = lay["hole"]
    r, b, bar = lay["radius"], lay["bezel"], lay["bar"]
    c0, c1 = accent[:2]
    if lay["kind"] == "ios":
        frame = (f'<div class="f" style="left:{x - b}px;top:{y - b}px;width:{w + 2 * b}px;height:{h + 2 * b}px;'
                 f'border-radius:{r + b}px;background:#0c0d12;box-shadow:0 0 0 3px #3a3d48,0 40px 90px rgba(0,0,0,.45)"></div>')
    elif lay["kind"] == "web":
        frame = (f'<div class="f" style="left:{x}px;top:{y - bar}px;width:{w}px;height:{h + bar}px;border-radius:{r}px;'
                 f'background:#1e1f26;box-shadow:0 40px 90px rgba(0,0,0,.45)">'
                 f'<div class="dots"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></div>'
                 f'<div class="url">{label}</div></div>')
    else:
        frame = (f'<div class="f" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;border-radius:{r}px;'
                 f'background:#000;box-shadow:0 40px 90px rgba(0,0,0,.45)"></div>')
    return f"""<!doctype html><meta charset="utf-8"><style>
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden}}
body{{background:linear-gradient(135deg,{c0},{c1});font-family:{cards.FONT}}}
.f{{position:absolute}}
.dots{{position:absolute;left:28px;top:26px;display:flex;gap:16px}}
.dots i{{display:block;width:22px;height:22px;border-radius:50%}}
.url{{position:absolute;left:50%;top:14px;transform:translateX(-50%);min-width:40%;padding:10px 28px;
border-radius:12px;background:#2c2e37;color:#c9ccd6;font-size:26px;text-align:center}}
</style>{frame}"""


def build(raw: Path, out: Path, kind: str, accent: list, label: str = "") -> dict:
    """Writes out (stage video, 2880x1620 @30fps); returns the layout for mapping coordinates."""
    src_w, src_h, dur = _probe(raw)
    lay = layout(kind, src_w, src_h)
    x, y, w, h = lay["hole"]
    r = lay["radius"]
    with tempfile.TemporaryDirectory() as tmp:
        under = Path(tmp) / "under.png"
        page = Path(tmp) / "under.html"
        page.write_text(_underlay_html(lay, accent, label))
        subprocess.run([cards.chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1", f"--window-size={W},{H}",
                        f"--user-data-dir={tmp}/profile", f"--screenshot={under}", page.as_uri()],
                       check=True, capture_output=True, timeout=60)
        # Rounded-corner alpha for the recording, drawn once: inside when the distance from the
        # inner rectangle is within the corner radius (top corners square under a web window bar).
        top_r = 0 if kind == "web" else r
        rr = f"if(lt(Y,{h // 2}),{top_r},{r})"
        dx = f"(max({rr}-X,0)+max(X-({w - 1}-{rr}),0))"
        dy = f"if(lt(Y,{h // 2}),max({rr}-Y,0),max(Y-({h - 1}-{rr}),0))"
        mask = Path(tmp) / "mask.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=white:s={w}x{h}",
                        "-frames:v", "1", "-vf", f"format=gray,geq=lum='if(lte(hypot({dx},{dy}),{rr}),255,0)'",
                        str(mask)], check=True)
        graph = (f"[1:v]fps={FPS},scale={w}:{h}:flags=lanczos,format=yuva420p[c];"
                 f"[2:v]format=gray[m];[c][m]alphamerge[cm];"
                 f"[0:v][cm]overlay={x}:{y}:shortest=1,format=yuv420p")
        loop = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}"]
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *loop, "-i", str(under),
                        "-i", str(raw), *loop, "-i", str(mask),
                        "-filter_complex", graph, "-c:v", "libx264", "-crf", "14",
                        "-preset", "medium", "-pix_fmt", "yuv420p", str(out)], check=True)
    return lay


def to_stage(lay: dict, px: float, py: float) -> tuple:
    """Raw recording pixel -> stage pixel."""
    x, y, _, _ = lay["hole"]
    return x + px * lay["scale"], y + py * lay["scale"]
