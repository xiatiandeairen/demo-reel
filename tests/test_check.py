"""Cases for sensitive-text detection and the GIF size ladder.

Integration cases run only with REEL_INTEGRATION=1 (bin/reel test --integration).
Fake secrets are assembled at run time so the repo itself holds none.
"""
import getpass
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from reel import cards, check, export

INTEGRATION = os.environ.get("REEL_INTEGRATION") == "1"
FAKE_GH = "ghp_" + "Ab3" * 12
FAKE_SK = "sk-" + "x9Y" * 9


class SensitiveText(unittest.TestCase):
    # CASE-A4.1
    def test_secrets_and_home_paths_are_found(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as cfg:
            (Path(cfg) / "demo-reel").mkdir()
            (Path(cfg) / "demo-reel" / "private.txt").write_text("# company hosts\n\\.corp\\.example\\b\n")
            old = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = cfg
            try:
                pats = check.patterns()
            finally:
                if old is None:
                    os.environ.pop("XDG_CONFIG_HOME")
                else:
                    os.environ["XDG_CONFIG_HOME"] = old
        for line, kind in [
            (f"export GITHUB_TOKEN={FAKE_GH}", "GitHub token"),
            (f"OPENAI_API_KEY={FAKE_SK}", "API key"),
            ("cd /Users/somebody/projects/app", "home path"),
            ("ssh build01.corp.example", "private pattern"),
        ]:
            with self.subTest(kind):
                self.assertIn(kind, [k for k, _ in check.find_sensitive([line], pats)])

    # CASE-A4.1
    def test_ordinary_code_is_not_flagged(self):
        pats = check.patterns(None)
        lines = ["aq run -- ./build.sh", "ok  build  0:04  reused:true", "task-key = sk_tests",
                 "fn main() { println!(\"hello\"); }", "/usr/local/bin/aq", "/Users/Shared/demo",
                 "$ git push origin main"]
        self.assertEqual(check.find_sensitive(lines, pats), [])

    @unittest.skipUnless(INTEGRATION, "integration")
    def test_ocr_reads_a_token_off_a_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "frame.png"
            cards.caption(png, f"token {FAKE_GH} in /Users/{getpass.getuser()}/app")
            lines = check.ocr([png])[str(png)]
            kinds = {k for k, _ in check.find_sensitive(lines, check.patterns(None))}
            self.assertIn("GitHub token", kinds)
            self.assertIn("home path", kinds)


@unittest.skipUnless(INTEGRATION, "integration")
class GifLadder(unittest.TestCase):
    # CASE-A4.2
    def test_steps_down_until_it_fits_and_records_each_try(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "noise.mp4"
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                            "cellauto=s=1920x1080:rule=110:rate=15,format=yuv420p", "-t", "4",
                            "-c:v", "libx264", str(src)], check=True)
            dst = Path(tmp) / "out.gif"
            first = export.gif(src, dst, max_bytes=1 << 40)
            cap = first[0]["bytes"] // 2
            tries = export.gif(src, dst, max_bytes=cap)
            self.assertGreater(len(tries), 1)
            self.assertEqual([t["width"] for t in tries], [w for w, _, _ in export.GIF_LADDER[:len(tries)]])
            self.assertEqual(tries[-1]["bytes"], dst.stat().st_size)
            for t in tries[:-1]:
                self.assertGreater(t["bytes"], cap)  # stops at the first size that fits
            if tries[-1]["bytes"] > cap:
                self.assertEqual(len(tries), len(export.GIF_LADDER))  # gave up only at the last step


if __name__ == "__main__":
    unittest.main()
