"""Integration cases for the aq walkthrough film (docs/multi-scene.md), read from its last recording.

Run after `reel make examples/aq/film.toml` with: REEL_INTEGRATION=1 python3 -m unittest tests.test_film_integration
(`reel test --integration` does this). They read the scenes' state directories; nothing is recorded here,
except CASE-C6.3, which composes the film again.
"""
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from reel import check, paths, screens, spec, timeline

ROOT = Path(__file__).resolve().parent.parent
AQ = ROOT / "examples" / "aq"
RUN = os.environ.get("REEL_INTEGRATION") == "1"


def state(name: str) -> Path:
    return paths.state_dir(spec.load(AQ / name))


def scene(name: str):
    st = state(name)
    if not (st / "events.json").exists():
        raise unittest.SkipTest(f"{name} has not been recorded")
    ev = json.loads((st / "events.json").read_text())
    tl = json.loads((st / "timeline.json").read_text())
    return st, ev, tl


def shown(tl: dict, t: float) -> bool:
    return timeline.output_time(tl["keep"], t) is not None


def film_time(tl: dict, t: float) -> float:
    """Film time of stage time t; a moment that was cut maps to where the film resumes."""
    at = timeline.output_time(tl["keep"], t)
    if at is not None:
        return at
    nxt = next(a for a, b in tl["keep"] if a > t)
    return timeline.output_time(tl["keep"], nxt)


def commands(ev: dict, text: str) -> list:
    return [c for c in ev["commands"] if text in c["cmd"].replace("\\ ", " ")]


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class SharedSimulator(unittest.TestCase):
    # CASE-C2: on the one shared simulator, A's page comes up and B's then replaces it, on screen.
    def test_b_pushes_a_off(self):
        st, ev, tl = scene("without-aq.toml")
        colours = screens.timeline(st / "stage.mp4", ev["regions"]["the only simulator"])
        a_cmd, b_cmd = commands(ev, "sim-open A")[0], commands(ev, "sim-open B")[0]
        t_a = screens.first(colours, "A", a_cmd["start"])
        t_b = screens.first(colours, "B", b_cmd["start"])
        self.assertIsNotNone(t_a, "Agent A's page never showed")
        self.assertIsNotNone(t_b, "Agent B's page never showed")
        self.assertLess(t_a, t_b)
        self.assertTrue(shown(tl, t_a + 0.3) and shown(tl, t_b + 0.3), "a page change was cut out of the film")


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class OwnSimulators(unittest.TestCase):
    # CASE-C3: in the scene's last 3 s, A's phone shows A's page and B's shows B's, at the same time.
    def test_each_keeps_its_own(self):
        st, ev, tl = scene("borrow.toml")
        end = tl["keep"][-1][1]
        for name, label in (("agent A's simulator", "A"), ("agent B's simulator", "B")):
            colours = screens.timeline(st / "stage.mp4", ev["regions"][name])
            tail = [v for t, v in colours if end - 3.0 <= t <= end - 0.2]
            self.assertTrue(tail and all(v == label for v in tail), f"{name}: {tail}")

    # CASE-C3.1: in the film, a phone changes only after its command was entered, and within 6 s
    # (film time). Safari's moving progress bar keeps a slow load from being cut as idle; while
    # recording, a page takes 3-5 s to load (under 1 s on an idle machine), so the bound is 6 s.
    def test_phones_follow_their_commands(self):
        for name, dev_of in (("without-aq.toml", {"A": "the only simulator", "B": "the only simulator"}),
                             ("borrow.toml", {"A": "agent A's simulator", "B": "agent B's simulator"})):
            st, ev, tl = scene(name)
            for label, dev in dev_of.items():
                cmd = commands(ev, f"sim-open {label}")[0]
                colours = screens.timeline(st / "stage.mp4", ev["regions"][dev])
                before = [v for t, v in colours if t < cmd["start"] - 0.1]
                if label in before:
                    continue  # the page was already up
                t = screens.first(colours, label)
                self.assertIsNotNone(t, f"{name}: {label}'s page never showed")
                self.assertGreaterEqual(t, cmd["start"] - 0.1, f"{name}: {label}'s page showed before its command")
                shown_at, typed_at = film_time(tl, t), film_time(tl, cmd["start"])
                self.assertLessEqual(shown_at - typed_at, 6.0, f"{name}: {label}'s page took over 6 s in the film")


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class ResultsCard(unittest.TestCase):
    # CASE-C5: the card's figures are what runs.log says, and the card shows them.
    def test_figures_match_the_logs(self):
        st = state("result.toml")
        if not (st / "card.json").exists():
            raise unittest.SkipTest("result.toml has not been made")
        runs = {k: [l.split() for l in Path(f"/tmp/aq-demo-{k}/runs.log").read_text().splitlines() if l.strip()]
                for k in ("without", "with")}
        want = [f"Builds run: {len(runs['without'])} → {len(runs['with'])}",
                "Build time: {} s → {} s".format(*(sum(int(b) - int(a) for a, b in runs[k]) for k in ("without", "with")))]
        self.assertEqual(json.loads((st / "card.json").read_text())["lines"], want)
        seen = " ".join(check.ocr([st / "card.png"])[str(st / "card.png")])
        for line in want:
            for number in re.findall(r"\d+", line):
                self.assertIn(number, seen)


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class Recompose(unittest.TestCase):
    # CASE-C6.3: composing the film again reuses every recorded scene.
    def test_compose_does_not_record_again(self):
        film = spec.load(AQ / "film.toml")
        stages = [paths.state_dir(spec.load(p)) / "stage.mp4" for p in film["_scenes"] if spec.load(p)["kind"] != "card"]
        if not all(s.exists() for s in stages):
            raise unittest.SkipTest("not every scene has been recorded")
        before = [s.stat().st_mtime for s in stages]
        subprocess.run([str(ROOT / "bin" / "reel"), "compose", str(AQ / "film.toml")], check=True, capture_output=True)
        self.assertEqual([s.stat().st_mtime for s in stages], before)


if __name__ == "__main__":
    unittest.main()
