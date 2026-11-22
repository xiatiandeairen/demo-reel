"""Integration cases for the on-screen step marker (REEL_INTEGRATION=1)."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from reel import record_terminal

INTEGRATION = os.environ.get("REEL_INTEGRATION") == "1"


@unittest.skipUnless(INTEGRATION, "integration")
class StepMarker(unittest.TestCase):
    # CASE-A2.1: step times come from the video itself, not an assumed frame rate
    def test_flips_are_found_at_their_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"
            # a dark frame whose marker cell switches between grey 38 and 68 at 1.0 s, 2.5 s and 4.0 s
            cell = "drawbox=x=100:y=100:w=40:h=60:t=fill:color=0x{c}{c}{c}"
            parts = [(1.0, "26"), (1.5, "44"), (1.5, "26"), (1.0, "44")]
            inputs, graph = [], []
            for i, (d, c) in enumerate(parts):
                inputs += ["-f", "lavfi", "-t", str(d), "-i", "color=c=0x1e1e2e:s=400x300:r=25"]
                graph.append(f"[{i}:v]{cell.format(c=c)}[p{i}]")
            graph.append("".join(f"[p{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1[v]")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(graph),
                            "-map", "[v]", "-pix_fmt", "yuv420p", str(video)], check=True)
            flips = record_terminal._mark_times(video, [100, 100, 140, 160])
            self.assertEqual(len(flips), 3)
            for got, want in zip(flips, [1.0, 2.5, 4.0]):
                self.assertAlmostEqual(got, want, delta=0.05)


if __name__ == "__main__":
    unittest.main()
