"""Unit cases for loading a reel (docs/design.md, "项目里的文件"). Run: python3 -m unittest discover tests"""
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from reel import spec

ROOT = Path(__file__).resolve().parent.parent

REEL = """
lang = "en"
[share]
scenes = ["intro", "main", "outro"]
[readme]
scenes = ["intro", "main"]
[gif]
scene = "main"
[card.outro]
lines = ["Try it"]
"""
MAIN = """
kind = "terminal"
[terminal]
workdir = "/tmp/x"
[[pane]]
name = "a"
[[step]]
pane = "a"
type = "echo hi"
say = "Say hi."
[[step]]
type = "echo again"
"""
INTRO = """
kind = "animation"
[animation]
html = "intro.html"
"""


def write(root: Path, reel=REEL, scenes=None) -> Path:
    d = root / ".agents" / "demo-reel" / "cli"
    shutil.rmtree(d, ignore_errors=True)
    (d / "scenes").mkdir(parents=True)
    (d / "reel.toml").write_text(textwrap.dedent(reel))
    for name, text in (scenes or {"main": MAIN, "intro": INTRO}).items():
        (d / "scenes" / f"{name}.toml").write_text(textwrap.dedent(text))
    return d / "reel.toml"


class LoadReel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def error(self, **kw) -> str:
        with self.assertRaises(spec.SpecError) as cm:
            spec.load(write(self.root, **kw))
        return str(cm.exception)

    # CASE-B10: a reel lives in <project>/.agents/demo-reel/<name>/; scenes are scenes/<id>.toml
    def test_reel_names_its_project_scenes_and_cuts(self):
        r = spec.load(write(self.root))
        self.assertEqual(r["name"], "cli")
        self.assertEqual(Path(r["project"]), self.root)
        self.assertEqual(r["cuts"], {"share": ["intro", "main", "outro"], "readme": ["intro", "main"], "gif": ["main"]})
        self.assertEqual(sorted(r["scenes"]), ["intro", "main"])
        self.assertEqual(spec.scene(r, "outro")["kind"], "card")

    def test_every_example_loads(self):
        reels = sorted(ROOT.glob("examples/*/*/reel.toml"))
        self.assertGreaterEqual(len(reels), 6)
        for p in reels:
            with self.subTest(p=p.relative_to(ROOT)):
                spec.load(p)

    def test_derived_terminal_values(self):
        sc = spec.load(write(self.root))["scenes"]["main"]
        self.assertEqual(sc["terminal"]["font_size"], 52)        # fewer than four panes
        self.assertEqual(sc["terminal"]["layout"], "tiled")      # no device beside the terminal
        self.assertNotIn("focus", sc["step"][1])                 # default: the pane typed in, framed tight
        self.assertFalse(sc["pane"][0]["noisy"])                 # no run: not a dashboard

    def test_four_panes_and_a_dashboard(self):
        main = MAIN.replace('[[pane]]\nname = "a"',
                            '[[pane]]\nname = "a"\n[[pane]]\nname = "b"\n[[pane]]\nname = "c"\n'
                            '[[pane]]\nname = "top"\nrun = "top"')
        sc = spec.load(write(self.root, scenes={"main": main, "intro": INTRO}))["scenes"]["main"]
        self.assertEqual(sc["terminal"]["font_size"], 40)
        self.assertEqual([p["noisy"] for p in sc["pane"]], [False, False, False, True])

    def test_a_removed_field_is_named_with_what_replaces_it(self):
        msg = self.error(scenes={"main": MAIN.replace('workdir = "/tmp/x"', 'workdir = "/tmp/x"\nsetup = "s.sh"'),
                                 "intro": INTRO})
        self.assertIn("cli/scenes/main.toml [terminal]: 'setup'", msg)
        self.assertIn("reset", msg)
        self.assertIn("'caption'", self.error(scenes={"main": MAIN.replace('say = "Say hi."', 'caption = "x"'),
                                                       "intro": INTRO}))
        self.assertIn("'title'", self.error(reel='title = "x"\n' + REEL))

    def test_cuts_name_only_known_scenes_and_the_gif_is_recorded(self):
        self.assertIn("no scene or card 'nope'", self.error(reel=REEL.replace('["intro", "main"]', '["nope"]')))
        self.assertIn("not the card 'outro'", self.error(reel=REEL.replace('scene = "main"', 'scene = "outro"')))
        self.assertIn("missing [gif]", self.error(reel=REEL.replace('[gif]\nscene = "main"', '')))

    def test_captions_start_on_the_first_step(self):
        msg = self.error(scenes={"main": MAIN.replace('say = "Say hi."\n', ''), "intro": INTRO})
        self.assertIn("step 1: needs say", msg)

    def test_scene_and_card_ids_do_not_collide(self):
        self.assertIn("also a card", self.error(scenes={"main": MAIN, "intro": INTRO, "outro": INTRO}))

    def test_devices_and_targets_are_named(self):
        ios = 'kind = "ios"\n[ios]\napp = "Settings"\n[[step]]\nclick = "General"\nsay = "Open it."\n'
        self.assertIn("[ios] needs device", self.error(scenes={"main": ios, "intro": INTRO}))
        both = ios.replace('app = "Settings"', 'app = "Settings"\ndevice = "$SIM"').replace(
            'click = "General"', 'click = "General"\nkey = "Enter"')
        self.assertIn("one action per step", self.error(scenes={"main": both, "intro": INTRO}))
        self.assertIn("focus 'nope'", self.error(scenes={"main": MAIN.replace('type = "echo again"',
                                                                               'type = "echo again"\nfocus = "nope"'),
                                                          "intro": INTRO}))


if __name__ == "__main__":
    unittest.main()
