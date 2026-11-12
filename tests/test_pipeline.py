import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import load_wav, save_wav          # noqa: E402
from guitarcoach.input import choose_profile                 # noqa: E402
from guitarcoach.ir import Detection, Note, Score, midi_to_freq  # noqa: E402
from guitarcoach.judge import LOOSE, judge_phrase            # noqa: E402
from guitarcoach.score_io import load_score, save_score      # noqa: E402
from guitarcoach.synth import SR, render                     # noqa: E402


class TestScoreIO(unittest.TestCase):
    def test_roundtrip(self):
        score = Score(title="t", notes=[
            Note(start=0.0, dur=0.4, midi=55, string=3, fret=0),
            Note(start=0.5, dur=0.4, midi=57, string=3, fret=2, tech="slide"),
        ])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            save_score(score, p)
            back = load_score(p)
        self.assertEqual(back.title, "t")
        self.assertEqual(len(back.notes), 2)
        self.assertEqual(back.notes[1].tech, "slide")
        self.assertEqual(back.notes[1].midi, 57)

    def test_derives_midi_from_string_fret(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text('{"notes":[{"start":0,"string":1,"fret":3}]}',
                         encoding="utf-8")
            score = load_score(p)
        self.assertEqual(score.notes[0].midi, 67)   # G4


class TestAudioIO(unittest.TestCase):
    def test_roundtrip(self):
        t = np.arange(int(0.2 * SR)) / SR
        x = 0.5 * np.sin(2 * np.pi * 220.0 * t)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.wav"
            save_wav(p, x, SR)
            y, sr = load_wav(p)
        self.assertEqual(sr, SR)
        self.assertAlmostEqual(len(y), len(x), delta=2)
        self.assertLess(float(np.max(np.abs(y - x))), 0.01)


class TestInputProfiles(unittest.TestCase):
    def test_bluetooth_degrades_to_pitch_only(self):
        p = choose_profile(driver="wasapi", is_bluetooth=True, latency_ms=180)
        self.assertTrue(p.pitch_only)
        self.assertFalse(p.judge_onset)
        self.assertIsNotNone(p.warning)

    def test_midi_trusts_everything(self):
        p = choose_profile(has_midi=True, latency_ms=4)
        self.assertFalse(p.pitch_only)
        self.assertTrue(p.judge_string)

    def test_interface_and_builtin_differ(self):
        iface = choose_profile(driver="asio", latency_ms=12, channels=2)
        builtin = choose_profile(driver="wasapi", latency_ms=55, channels=1)
        self.assertTrue(iface.judge_string)
        self.assertFalse(builtin.judge_string)
        self.assertIsNotNone(builtin.warning)


class TestJudgeOnsetSwitch(unittest.TestCase):
    def test_jittery_input_wide_window(self):
        notes = [Note(start=1.0, dur=0.4, midi=55)]
        dets = [Detection(1.6, 55, cents=5)]        # 600 ms late
        self.assertEqual(judge_phrase(notes, dets, LOOSE)[0].status, "missed")

        from guitarcoach.judge import JudgeConfig
        relaxed = JudgeConfig(judge_onset=False)
        self.assertEqual(judge_phrase(notes, dets, relaxed)[0].status, "hit")


if __name__ == "__main__":
    unittest.main(verbosity=2)