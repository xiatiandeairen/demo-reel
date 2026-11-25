"""Unit cases for the app, page and window recorders' own rules (docs/design.md, 各端录制)."""
import unittest

from reel import record_app, record_mac, stage
from reel.record_terminal import RecordError


class Verbs(unittest.TestCase):
    # One set of step verbs for every app kind; each becomes its tool's own command.
    def test_phone_verbs_map_to_agent_device(self):
        self.assertEqual(record_app._args("click", 'text="General"'), ["click", 'text="General"'])
        self.assertEqual(record_app._args("fill", ["@e3", "hello"]), ["fill", "@e3", "hello"])
        self.assertEqual(record_app._args("back", True), ["back"])
        self.assertEqual(record_app._args("key", "Enter"), ["keyboard", "enter"])
        with self.assertRaisesRegex(RecordError, "only press Enter"):
            record_app._args("key", "cmd+k")

    def test_mac_capture_covers_every_step(self):
        steps = [{"hold": 1.5}, {"hold": 0.4, "_narration": 2.0}]
        self.assertEqual(record_mac.capture_seconds(steps), int(3 + 1.2 + (1.5 + 2.5) + (2.3 + 2.5)))


class CaptionBand(unittest.TestCase):
    # CASE-E11: a phone, page or window ends above the band where captions sit.
    def test_recordings_stay_above_the_captions(self):
        for kind, size in (("ios", (1206, 2622)), ("android", (1080, 2400)), ("web", (3200, 1800)), ("mac", (1400, 900))):
            with self.subTest(kind):
                x, y, w, h = stage.layout(kind, *size)["hole"]
                self.assertLessEqual(y + h, stage.H - stage.CAPTION_BAND)


if __name__ == "__main__":
    unittest.main()
