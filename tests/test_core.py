"""Unit cases for the timeline and the camera plan. Run: python3 -m unittest discover tests"""
import copy
import unittest

from reel import motion, timeline
from reel.motion import SMALL_H, SMALL_W, Activity, Beat

W, H = 2880, 1620


def good_timeline():
    return {
        "stage": {"path": "stage.mp4", "width": W, "height": H, "duration": 20.0, "fps": 15},
        "output": {"width": 1920, "height": 1080, "fps": 30},
        "keep": [[0, 8], [12, 20]],
        "shots": [{"t": 0, "x": 1440, "y": 810, "zoom": 1.0},
                  {"t": 2, "x": 720, "y": 405, "zoom": 2.0}],
        "captions": [{"start": 1, "end": 4, "text": "Two agents start the same build"}],
        "intro": {"seconds": 1.5, "title": "aq", "subtitle": "a queue"},
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
            "intro without title": (lambda d: d["intro"].pop("title"), "intro: missing 'title'"),
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
        self.assertEqual(len(shots), 3)  # start, then one move into the pane

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
