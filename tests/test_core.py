"""Unit cases for the timeline and the camera plan. Run: python3 -m unittest discover tests"""
import copy
import unittest

from reel import motion, timeline
from reel.motion import SMALL_H, SMALL_W, Activity, Beat

W, H = 2880, 1620


def good_timeline():
    return {
        "stage": {"path": "stage.mp4", "width": W, "height": H, "duration": 20.0, "fps": 15},
        "keep": [[0, 8], [12, 20]],
        "shots": [{"t": 0, "x": 1440, "y": 810, "zoom": 1.0},
                  {"t": 2, "x": 720, "y": 405, "zoom": 2.0}],
        "captions": [{"start": 1, "end": 4, "text": "Two agents start the same build"}],
    }


class TimelineValidation(unittest.TestCase):
    # CASE-A1.1
    def test_good_timeline_passes(self):
        timeline.validate(good_timeline())

    # CASE-A1.1
    def test_each_broken_field_is_named(self):
        broken = {
            "missing shots": (lambda d: d.pop("shots"), "missing 'shots'"),
            "shots out of order": (lambda d: d["shots"].reverse(), "before the previous shot"),
            "view leaves the stage": (lambda d: d["shots"][1].update(x=100), "goes outside"),
            "zoom too far": (lambda d: d["shots"][1].update(zoom=5), "outside 1..3"),
            "overlapping keep": (lambda d: d["keep"].append([5, 9]), "before the previous part ends"),
            "keep past the end": (lambda d: d["keep"].__setitem__(1, [12, 25]), "is not inside"),
            "caption backwards": (lambda d: d["captions"][0].update(end=0.5), "captions[0]"),
        }
        for name, (breaker, message) in broken.items():
            with self.subTest(name):
                d = copy.deepcopy(good_timeline())
                breaker(d)
                with self.assertRaises(timeline.TimelineError) as ctx:
                    timeline.validate(d)
                self.assertIn(message, str(ctx.exception))

    def test_output_time_skips_cuts(self):
        keep = [[0, 8], [12, 20]]
        self.assertEqual(timeline.output_time(keep, 5), 5)
        self.assertIsNone(timeline.output_time(keep, 10))
        self.assertEqual(timeline.output_time(keep, 13), 9)


def activity_with(changes, seconds=10, fps=10):
    """Masks where each (t0, t1, stage rect) area changes in every sample between t0 and t1."""
    masks = [bytearray(SMALL_W * SMALL_H) for _ in range(int(seconds * fps) + 1)]
    for t0, t1, (x0, y0, x1, y1) in changes:
        sx, sy = SMALL_W / W, SMALL_H / H
        for i in range(int(t0 * fps), int(t1 * fps) + 1):
            for y in range(int(y0 * sy), int(y1 * sy)):
                for x in range(int(x0 * sx), int(x1 * sx)):
                    masks[i][y * SMALL_W + x] = 1
    return Activity(masks, W, H, fps)


TOP_LEFT = (80, 80, 1440, 810)
BOTTOM_RIGHT = (1440, 810, 2800, 1540)


class CameraPlan(unittest.TestCase):
    # CASE-A2.2
    def test_frames_the_area_that_changed(self):
        act = activity_with([(1, 4, (200, 200, 900, 500))])
        box = act.bbox(0, 5)
        cell = W / SMALL_W  # analysis is accurate to one small pixel
        self.assertLessEqual(box[0], 200 + cell)
        self.assertLessEqual(box[1], 200 + cell)
        self.assertGreaterEqual(box[2], 900 - cell)
        self.assertGreaterEqual(box[3], 500 - cell)
        cam = motion.frame(box, W, H)
        half_w, half_h = W / cam["zoom"] / 2, H / cam["zoom"] / 2
        self.assertTrue(cam["x"] - half_w <= 200 and cam["x"] + half_w >= 900)
        self.assertTrue(cam["y"] - half_h <= 200 and cam["y"] + half_h >= 500)
        self.assertGreater(cam["zoom"], 1.5)

    # CASE-A2.2
    def test_ignored_area_does_not_pull_the_camera(self):
        act = activity_with([(1, 4, (200, 200, 900, 500)), (0, 10, BOTTOM_RIGHT)])
        box = act.bbox(0, 5, ignore=[BOTTOM_RIGHT])
        self.assertLess(box[2], 1440)

    # CASE-A2.3
    def test_two_panes_changing_together_get_one_wide_shot(self):
        act = activity_with([(1, 9, TOP_LEFT), (1, 9, BOTTOM_RIGHT)])
        beats = [Beat(1, 4), Beat(4, 6), Beat(6, 9)]
        shots, _ = motion.plan(beats, act, 10)
        self.assertEqual({s["zoom"] for s in shots}, {1.0})

    # CASE-A2.3
    def test_most_of_the_stage_changing_is_shown_full_not_nudged(self):
        cam = motion.frame((300, 200, 2400, 1400), W, H)  # ~55% of the stage
        self.assertEqual(cam["zoom"], 1.0)

    # CASE-A2.3
    def test_same_framing_in_a_row_does_not_move(self):
        act = activity_with([(1, 9, TOP_LEFT)])
        beats = [Beat(2, 4, focus=[TOP_LEFT]), Beat(4, 6, focus=[TOP_LEFT]), Beat(6, 9, focus=[TOP_LEFT])]
        shots, _ = motion.plan(beats, act, 10)
        framings = [(s["x"], s["y"], s["zoom"]) for s in shots]
        changes = sum(1 for a, b in zip(framings, framings[1:]) if a != b)
        self.assertEqual(changes, 2)  # one move into the pane, one back to full at the end

    # CASE-B2.1
    def test_tight_framing_zooms_on_the_changed_line_not_the_whole_pane(self):
        line = (120, 300, 900, 360)  # one line of output near the top of the top-left pane
        act = activity_with([(1, 4, line)])
        pane_cam = motion.frame(TOP_LEFT, W, H)
        shots, _ = motion.plan([Beat(1, 4, focus=[TOP_LEFT], tight=True)], act, 10)
        cam = max(shots, key=lambda s: s["zoom"])
        self.assertGreater(cam["zoom"], pane_cam["zoom"])
        half_w = W / cam["zoom"] / 2
        self.assertLessEqual(cam["x"] - half_w, TOP_LEFT[0] + 1)  # left edge of the pane stays in view
        self.assertGreaterEqual(cam["x"] + half_w, line[2] - W / SMALL_W)

    # CASE-B2.1: framing a pane of the right column shows none of the left column's pane (no half words).
    def test_view_stays_inside_the_framed_pane(self):
        right = (1907, 219, 3701, 1025)          # the top-right pane of the aq grid (stage pixels)
        cam = motion.frame((1907, 300, 3252, 420), 3840, 2160, 2.5, within=right)
        half_w = 3840 / cam["zoom"] / 2
        self.assertGreaterEqual(cam["x"] - half_w, right[0] - motion.EDGE)
        self.assertLessEqual(cam["x"] + half_w, right[2] + motion.EDGE)

    # CASE-B2
    def test_film_ends_on_the_whole_stage(self):
        act = activity_with([(1, 4, TOP_LEFT)])
        shots, _ = motion.plan([Beat(1, 8, focus=[TOP_LEFT])], act, 10)
        self.assertEqual(shots[-1]["zoom"], 1.0)
        self.assertGreater(len(shots), 3)

    def test_narrated_seconds_are_never_cut(self):
        act = activity_with([(1, 2, TOP_LEFT), (8, 9, TOP_LEFT)], seconds=10)
        _, keep = motion.plan([Beat(0.5, 10, focus=[TOP_LEFT], protect=6.0)], act, 10)
        for a, b in zip(keep, keep[1:]):
            self.assertGreaterEqual(a[1], 6.5)  # nothing removed before 0.5 + 6.0

    def test_long_stillness_is_cut_short_stillness_kept(self):
        act = activity_with([(1, 2, TOP_LEFT), (8, 9, TOP_LEFT)], seconds=10)
        _, keep = motion.plan([Beat(0.5, 10, focus=[TOP_LEFT])], act, 10)
        self.assertGreater(len(keep), 1)
        kept = timeline.kept_seconds(keep)
        self.assertLess(kept, 6.5)
        act2 = activity_with([(1, 2, TOP_LEFT), (3, 9, TOP_LEFT)], seconds=10)
        _, keep2 = motion.plan([Beat(0.5, 10, focus=[TOP_LEFT])], act2, 10)
        self.assertEqual(keep2, [[0.0, 10]])


if __name__ == "__main__":
    unittest.main()


class PresenterCaptions(unittest.TestCase):
    # CASE-B8.1
    def test_speech_is_cut_into_short_lines(self):
        from reel.narrate import CHUNK_WORDS, chunk_words
        words, t = [], 0.0
        for w in "This is the queue. It runs heavy builds one at a time and lends every agent its own device".split():
            words.append((t, t + 0.25, " " + w))
            t += 0.3
        words.append((t + 1.5, t + 1.8, " Done."))  # after a long pause
        lines = chunk_words(words)
        self.assertEqual(lines[0]["text"], "This is the queue.")  # sentence end
        self.assertTrue(all(len(l["text"].split()) <= CHUNK_WORDS for l in lines))
        self.assertEqual(lines[-1]["text"], "Done.")  # the pause starts a new line
        for a, b in zip(lines, lines[1:]):
            self.assertLessEqual(a["end"], b["start"])  # never two lines at once


class Storage(unittest.TestCase):
    # CASE-B10: a reel's state and deliverables follow XDG; the GIF goes to <project>/assets/<name>.gif;
    # the same reel in two worktrees gets two directories.
    def test_xdg_locations_and_distinct_names(self):
        import os
        import tempfile
        from pathlib import Path
        from reel import paths
        with tempfile.TemporaryDirectory() as home:
            old = {k: os.environ.get(k) for k in ("XDG_STATE_HOME", "XDG_DATA_HOME")}
            os.environ["XDG_STATE_HOME"], os.environ["XDG_DATA_HOME"] = f"{home}/state", f"{home}/data"
            try:
                a = {"name": "cli", "project": "/w/agent-quay", "_path": "/w/agent-quay/.agents/demo-reel/cli/reel.toml"}
                b = {"name": "cli", "project": "/w/agent-quay-feat", "_path": "/w/agent-quay-feat/.agents/demo-reel/cli/reel.toml"}
                sa, sb = paths.state_dir(a), paths.state_dir(b)
                self.assertNotEqual(sa, sb)
                self.assertTrue(sa.name.startswith("agent-quay-cli-"))
                self.assertEqual(paths.take_dir(a, "with"), sa / "scenes" / "with" / "take")
                self.assertEqual(paths.cut_dir(a, "share"), sa / "cuts" / "share")
                self.assertEqual(paths.data_dir(a), Path(f"{home}/data/demo-reel") / sa.name)
                self.assertEqual(paths.gif_path(a), Path("/w/agent-quay/assets/cli.gif"))
                self.assertNotIn("/w/", str(sa))
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
