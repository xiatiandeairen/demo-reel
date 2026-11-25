"""Unit cases for delivering: the GIF in the project, stale deliverables (docs/design.md, 导出、检查)."""
import tempfile
import unittest
from pathlib import Path

from reel import cli, paths


class PlaceGif(unittest.TestCase):
    # CASE-B10: the GIF goes to <project>/assets/<name>.gif, and never over a file demo-reel did not write.
    def test_gif_is_written_once_and_kept_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reel = {"name": "cli", "project": str(root), "_path": str(root / ".agents/demo-reel/cli/reel.toml")}
            pending = root / "pending.gif"
            pending.write_bytes(b"GIF89a one")
            report = {}
            dst = cli._place_gif(reel, pending, report, previous={})
            self.assertEqual(Path(dst), root / "assets" / "cli.gif")
            pending.write_bytes(b"GIF89a two")
            cli._place_gif(reel, pending, {}, previous=report)            # ours: replaced
            self.assertEqual((root / "assets" / "cli.gif").read_bytes(), b"GIF89a two")
            (root / "assets" / "cli.gif").write_bytes(b"someone else's")
            with self.assertRaises(cli.Failed) as cm:                     # changed by someone: left alone
                cli._place_gif(reel, pending, {}, previous=report)
            self.assertIn("not written by demo-reel", cm.exception.reason)
            self.assertEqual((root / "assets" / "cli.gif").read_bytes(), b"someone else's")


class Fresh(unittest.TestCase):
    # CASE-E5: a deliverable not made from its cut's latest stamp fails the checks.
    def test_stale_deliverable_is_named(self):
        made = {"share.mp4": {"cut": "share", "cut_stamp": "a"}, "readme.mp4": {"cut": "readme", "cut_stamp": "b"}}
        stamps = {"share": "a", "readme": "c"}
        from reel.check import stale
        self.assertEqual(stale(made, stamps), ["readme.mp4"])


if __name__ == "__main__":
    unittest.main()
