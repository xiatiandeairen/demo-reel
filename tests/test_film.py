"""Unit cases for films made of scenes (docs/multi-scene.md). Run: python3 -m unittest discover tests"""
import tempfile
import unittest
from pathlib import Path

from reel import film, record_card, spec
from reel.record_terminal import device_placement


def write(d: Path, name: str, text: str) -> Path:
    p = d / name
    p.write_text(text)
    return p


SCENE = 'title = "s"\nkind = "card"\n[card]\nlines = ["hi"]\n'


class FilmSpec(unittest.TestCase):
    # CASE-C6.1
    def test_scene_paths_are_relative_to_the_film(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "sub").mkdir()
            write(d / "sub", "a.toml", SCENE)
            f = write(d, "film.toml", 'title = "f"\n[[scene]]\nspec = "sub/a.toml"\n')
            s = spec.load(f)
            self.assertEqual(s["kind"], "film")
            self.assertEqual(s["_scenes"], [str((d / "sub" / "a.toml").resolve())])

    # CASE-C6.1
    def test_missing_scene_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = write(Path(tmp), "film.toml", 'title = "f"\n[[scene]]\nspec = "gone.toml"\n')
            with self.assertRaisesRegex(spec.SpecError, "gone.toml"):
                spec.load(f)

    # CASE-C6.1
    def test_film_inside_a_film_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write(d, "inner.toml", 'title = "i"\n[[scene]]\nspec = "x.toml"\n')
            f = write(d, "film.toml", 'title = "f"\n[[scene]]\nspec = "inner.toml"\n')
            with self.assertRaisesRegex(spec.SpecError, "inner.toml.*film"):
                spec.load(f)


class Stitching(unittest.TestCase):
    # CASE-C6.2
    def test_scenes_overlap_by_one_crossfade(self):
        starts, total = film.scene_starts([6.0, 10.0, 4.0], 0.4)
        self.assertEqual(starts, [0.0, 5.6, 15.2])
        self.assertAlmostEqual(total, 19.2)

    # CASE-C6.2
    def test_narration_moves_with_its_scene(self):
        items = film.shift_items([[("a.wav", 0.5)], [], [("b.wav", 1.0), ("c.wav", 3.0)]], [0.0, 5.6, 15.2])
        self.assertEqual(items, [("a.wav", 0.5), ("b.wav", 16.2), ("c.wav", 18.2)])

    # CASE-C8
    def test_failed_scene_is_named_and_earlier_scenes_are_kept(self):
        made = []

        def make(path):
            if path.endswith("borrow.toml"):
                raise RuntimeError("step 3 failed: waited for 'held'")
            made.append(path)

        with self.assertRaisesRegex(film.FilmError, r"borrow\.toml.*step 3 failed"):
            film.make_all(["/x/problem.toml", "/x/borrow.toml", "/x/install.toml"], make)
        self.assertEqual(made, ["/x/problem.toml"])


class CardValues(unittest.TestCase):
    # CASE-C5.1
    def test_values_come_from_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), "runs.log", "1 2\n3 4\n5 6\n")
            vals = record_card.values({"n": "wc -l < runs.log | tr -d ' '"}, tmp)
            self.assertEqual(record_card.fill(["Builds run: {n} → 1"], vals), ["Builds run: 3 → 1"])

    # CASE-C5.1
    def test_failing_or_empty_command_stops_the_film(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(record_card.CardError, "n"):
                record_card.values({"n": "cat missing.log"}, tmp)
            with self.assertRaisesRegex(record_card.CardError, "empty"):
                record_card.values({"n": "true"}, tmp)

    # CASE-C5.1
    def test_unknown_placeholder_is_named(self):
        with self.assertRaisesRegex(record_card.CardError, "missing_value"):
            record_card.fill(["{missing_value}"], {})


class DeviceSync(unittest.TestCase):
    # CASE-C3.2
    def test_device_started_after_the_terminal_is_delayed(self):
        self.assertEqual(device_placement(105.25, 100.0), (5.25, 0.0))

    # CASE-C3.2
    def test_device_started_before_the_terminal_is_trimmed(self):
        self.assertEqual(device_placement(97.5, 100.0), (0.0, 2.5))


class Squeeze(unittest.TestCase):
    # CASE-C3.3: a step marked squeeze loses the middle of its command's run, even while the screen moves.
    def test_span_is_the_commands_run_minus_both_ends(self):
        from reel.planner import squeeze_spans
        steps = [{"pane": "agent A", "type": "sim-open A", "squeeze": True}]
        beats = [{"start": 10.0, "end": 20.0, "narration": 0.0}]
        cmds = [{"pane": "agent A", "start": 10.6, "end": 16.0, "cmd": "sim-open A"}]
        self.assertEqual(squeeze_spans(steps, beats, cmds), [(11.1, 14.5)])

    # CASE-C3.3
    def test_narration_and_short_runs_are_kept(self):
        from reel.planner import squeeze_spans
        steps = [{"pane": "a", "type": "x", "squeeze": True}, {"pane": "a", "type": "y", "squeeze": True},
                 {"pane": "a", "type": "z"}]
        beats = [{"start": 0.0, "end": 9.0, "narration": 3.0}, {"start": 9.0, "end": 12.0, "narration": 0.0},
                 {"start": 12.0, "end": 30.0, "narration": 0.0}]
        cmds = [{"pane": "a", "start": 0.5, "end": 8.0}, {"pane": "a", "start": 9.5, "end": 11.0},
                {"pane": "a", "start": 12.5, "end": 29.0}]
        # step 1 keeps its narration (until 3.2 s); step 2 runs too briefly; step 3 is not marked
        self.assertEqual(squeeze_spans(steps, beats, cmds), [(3.2, 6.5)])

    # CASE-C3.3
    def test_spans_come_out_of_keep(self):
        from reel.planner import cut_spans
        self.assertEqual(cut_spans([[0.0, 10.0], [12.0, 20.0]], [(3.0, 5.0), (11.0, 14.0)]),
                         [[0.0, 3.0], [5.0, 10.0], [14.0, 20.0]])


class KeepTimeAndTimers(unittest.TestCase):
    # CASE-D1.1: a step marked keep_time (or timer) keeps its command's whole run, cut nowhere.
    def test_command_run_is_put_back_into_keep(self):
        from reel.planner import add_spans, keep_spans
        steps = [{"pane": "a", "type": "time xcodebuild build", "timer": "xcodebuild"}, {"pane": "a", "type": "ls"}]
        beats = [{"start": 2.0, "end": 14.0}, {"start": 14.0, "end": 20.0}]
        cmds = [{"pane": "a", "start": 2.4, "end": 11.0}, {"pane": "a", "start": 14.3, "end": 14.5}]
        spans = keep_spans(steps, beats, cmds)
        self.assertEqual(spans, [(2.4, 11.0)])
        self.assertEqual(add_spans([[0.0, 4.0], [7.0, 8.0], [12.0, 20.0]], spans), [[0.0, 11.0], [12.0, 20.0]])

    # CASE-D1.2: each timer runs over its command, rows in step order, one shared scale.
    def test_timers_come_from_commands(self):
        from reel.planner import timer_items
        steps = [{"pane": "a", "type": "x", "timer": "xcodebuild"}, {"pane": "a", "type": "y", "timer": "agb"}]
        beats = [{"start": 0.0, "end": 10.0}, {"start": 10.0, "end": 14.0}]
        cmds = [{"pane": "a", "start": 0.5, "end": 8.9}, {"pane": "a", "start": 10.4, "end": 11.9}]
        self.assertEqual(timer_items(steps, beats, cmds, 10.0),
                         [{"label": "xcodebuild", "start": 0.5, "end": 8.9, "seconds": 8.4, "scale": 10.0, "row": 0},
                          {"label": "agb", "start": 10.4, "end": 11.9, "seconds": 1.5, "scale": 10.0, "row": 1}])

    # CASE-D1.2: the bar grows in real time and stops at its share of the scale.
    def test_bar_width_follows_time(self):
        from reel.compose_ffmpeg import timer_width
        self.assertEqual(timer_width(0.0, start=1.0, seconds=8.4, scale=10.0, track=1000), 0)
        self.assertEqual(timer_width(5.0, start=1.0, seconds=8.4, scale=10.0, track=1000), 400)
        self.assertEqual(timer_width(30.0, start=1.0, seconds=8.4, scale=10.0, track=1000), 840)
        self.assertEqual(timer_width(30.0, start=1.0, seconds=14.0, scale=10.0, track=1000), 1000)


    # CASE-D1.2: the previous step's short command inside the window is not taken for the timed one.
    def test_timer_matches_the_typed_command(self):
        from reel.planner import timer_items
        steps = [{"type": "cd ../app-feature"}, {"type": "agb xcodebuild build", "timer": "new worktree"}]
        beats = [{"start": 13.9, "end": 14.6}, {"start": 14.6, "end": 20.0}]
        cmds = [{"pane": "main", "start": 14.3, "end": 14.31, "cmd": "cd ../app-feature"},
                {"pane": "main", "start": 18.2, "end": 19.7, "cmd": "agb\\ xcodebuild\\ build"}]
        self.assertEqual(timer_items(steps, beats, cmds, 6.0)[0]["seconds"], 1.5)


class BarCard(unittest.TestCase):
    # CASE-D1.3: bars in a group are as long as their values, the largest filling the track.
    def test_bar_lengths_are_proportional(self):
        from reel.record_card import bar_groups
        groups = [{"title": "First build in a new worktree", "unit": "s",
                   "items": [{"label": "xcodebuild", "value": "echo 8.4"}, {"label": "agb", "value": "echo 1.5"}]}]
        out = bar_groups(groups, ".")
        self.assertEqual([round(i["share"], 3) for i in out[0]["items"]], [1.0, 0.179])
        self.assertEqual([i["text"] for i in out[0]["items"]], ["8.4 s", "1.5 s"])

    # CASE-D1.3: a value that is not a number stops the film.
    def test_non_numeric_value_is_refused(self):
        from reel.record_card import CardError, bar_groups
        with self.assertRaisesRegex(CardError, "xcodebuild"):
            bar_groups([{"title": "t", "items": [{"label": "xcodebuild", "value": "echo fast"}]}], ".")


if __name__ == "__main__":
    unittest.main()
