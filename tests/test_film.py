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


if __name__ == "__main__":
    unittest.main()
