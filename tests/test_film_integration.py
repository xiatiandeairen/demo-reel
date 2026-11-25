"""Integration cases for the aq reel (examples/aq/cli), read from its last recording.

Run after `bin/reel make examples/aq/cli/reel.toml` with:
REEL_INTEGRATION=1 python3 -m unittest tests.test_film_integration
They read the scenes' takes and edits; nothing is recorded here. CASE-C6.3 runs reel make again and
expects every take to be reused.
"""
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from reel import check, paths, screens, spec, timeline

ROOT = Path(__file__).resolve().parent.parent
AQ = ROOT / "examples" / "aq" / "cli" / "reel.toml"
RUN = os.environ.get("REEL_INTEGRATION") == "1"


def reel() -> dict:
    return spec.load(AQ)


def scene(sid: str):
    """(take dir, events, timeline) of a recorded scene."""
    r = reel()
    take, edit = paths.take_dir(r, sid), paths.edit_dir(r, sid)
    if not (take / "events.json").exists() or not (edit / "timeline.json").exists():
        raise unittest.SkipTest(f"{sid} has not been recorded")
    return take, json.loads((take / "events.json").read_text()), json.loads((edit / "timeline.json").read_text())


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
        st, ev, tl = scene("without")
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
        st, ev, tl = scene("borrow")
        end = tl["keep"][-1][1]
        for name, label in (("agent A's simulator", "A"), ("agent B's simulator", "B")):
            colours = screens.timeline(st / "stage.mp4", ev["regions"][name])
            tail = [v for t, v in colours if end - 3.0 <= t <= end - 0.2]
            self.assertTrue(tail and all(v == label for v in tail), f"{name}: {tail}")

    # CASE-C3.1: in the film, a phone changes only after its command was entered, and within 3 s
    # (film time; the sim-open steps are marked squeeze, so a slow page load is cut although Safari's
    # progress bar moves).
    def test_phones_follow_their_commands(self):
        for name, dev_of in (("without", {"A": "the only simulator", "B": "the only simulator"}),
                             ("borrow", {"A": "agent A's simulator", "B": "agent B's simulator"})):
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
                self.assertLessEqual(shown_at - typed_at, 3.0, f"{name}: {label}'s page took over 3 s in the film")


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class ResultsCard(unittest.TestCase):
    # CASE-C5: the card's figures are what the scenes' kept runs.log say, and the card shows them.
    def test_figures_match_the_logs(self):
        r = reel()
        card = paths.edit_dir(r, "result")
        if not (card / "card.json").exists():
            raise unittest.SkipTest("the result card has not been made")
        runs = {k: [l.split() for l in (paths.take_dir(r, k) / "files" / "runs.log").read_text().splitlines() if l.strip()]
                for k in ("without", "with")}
        want = [f"Builds run: {len(runs['without'])} → {len(runs['with'])}",
                "Build time: {} s → {} s".format(*(sum(int(b) - int(a) for a, b in runs[k]) for k in ("without", "with")))]
        self.assertEqual(json.loads((card / "card.json").read_text())["lines"], want)
        seen = " ".join(check.ocr([card / "card.png"])[str(card / "card.png")])
        for line in want:
            for number in re.findall(r"\d+", line):
                self.assertIn(number, seen)


@unittest.skipUnless(RUN, "set REEL_INTEGRATION=1")
class Remake(unittest.TestCase):
    # CASE-C6.3, CASE-D5: reel make again with nothing changed records no scene again.
    def test_make_does_not_record_again(self):
        r = reel()
        stages = [paths.take_dir(r, sid) / "stage.mp4" for sid in r["scenes"]]
        if not all(s.exists() for s in stages):
            raise unittest.SkipTest("not every scene has been recorded")
        before = [s.stat().st_mtime for s in stages]
        out = subprocess.run([str(ROOT / "bin" / "reel"), "make", str(AQ)], capture_output=True, text=True)
        self.assertEqual([s.stat().st_mtime for s in stages], before, out.stdout[-800:])


if __name__ == "__main__":
    unittest.main()
