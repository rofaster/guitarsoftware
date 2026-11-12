import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import detect_notes, yin_pitch          # noqa: E402
from guitarcoach.ir import (Note, Detection, freq_to_midi,     # noqa: E402
                            midi_to_freq, midi_to_name,
                            note_from_string_fret)
from guitarcoach.judge import LOOSE, STRICT, judge_phrase, summarize  # noqa: E402
from guitarcoach.synth import SR, render                        # noqa: E402


class TestIR(unittest.TestCase):
    def test_string_fret(self):
        self.assertEqual(note_from_string_fret(6, 0), 40)   # low E
        self.assertEqual(note_from_string_fret(1, 0), 64)   # high E
        self.assertEqual(note_from_string_fret(3, 5), 60)   # C4 on G string

    def test_midi_names(self):
        self.assertEqual(midi_to_name(40), "E2")
        self.assertEqual(midi_to_name(69), "A4")
        self.assertEqual(midi_to_name(60), "C4")

    def test_freq_roundtrip(self):
        for m in (40, 55, 64, 69):
            self.assertAlmostEqual(freq_to_midi(midi_to_freq(m)), m, places=6)


class TestYin(unittest.TestCase):
    def test_pure_tone(self):
        t = np.arange(int(0.15 * SR)) / SR
        x = np.sin(2 * np.pi * 110.0 * t)
        f0 = yin_pitch(x, SR)
        self.assertAlmostEqual(f0, 110.0, delta=1.5)

    def test_silence_is_unvoiced(self):
        self.assertEqual(yin_pitch(np.zeros(2048), SR), 0.0)


class TestJudge(unittest.TestCase):
    def setUp(self):
        self.notes = [
            Note(start=1.0, dur=0.4, midi=55, string=3, fret=0),
            Note(start=2.0, dur=0.4, midi=57, string=3, fret=2),
            Note(start=3.0, dur=0.4, midi=59, string=3, fret=4),
        ]

    def test_all_hit(self):
        dets = [Detection(1.02, 55), Detection(2.0, 57), Detection(3.05, 59)]
        v = judge_phrase(self.notes, dets, LOOSE)
        self.assertEqual([x.status for x in v], ["hit", "hit", "hit"])
        self.assertEqual(summarize(v).accuracy, 1.0)

    def test_sharp_note_is_wrong(self):
        dets = [Detection(1.0, 56, cents=20)]     # 120 cents sharp
        v = judge_phrase(self.notes[:1], dets, LOOSE)
        self.assertEqual(v[0].status, "wrong_pitch")
        self.assertAlmostEqual(v[0].cents, 120.0, places=3)

    def test_late_beyond_window_is_missed(self):
        dets = [Detection(1.4, 55)]               # +400 ms, outside +350
        v = judge_phrase(self.notes[:1], dets, LOOSE)
        self.assertEqual(v[0].status, "missed")

    def test_loose_tolerates_what_strict_rejects(self):
        dets = [Detection(1.01, 55, cents=45)]    # 45 cents off
        self.assertEqual(judge_phrase(self.notes[:1], dets, LOOSE)[0].status, "hit")
        self.assertEqual(judge_phrase(self.notes[:1], dets, STRICT)[0].status,
                         "wrong_pitch")

    def test_tech_note_is_skipped(self):
        n = Note(start=1.0, dur=0.4, midi=55, tech="bend")
        v = judge_phrase([n], [], LOOSE)
        self.assertEqual(v[0].status, "skipped")


class TestEndToEnd(unittest.TestCase):
    def test_synth_to_judge(self):
        notes = [Note(start=i * 0.6, dur=0.4, midi=55 + 2 * i, string=3, fret=2 * i)
                 for i in range(3)]
        events = [(n.start, midi_to_freq(n.midi), 0.5, i)
                  for i, n in enumerate(notes)]
        audio = render(events, 2.6)
        dets = detect_notes(audio, SR)
        self.assertGreaterEqual(len(dets), 3)
        v = judge_phrase(notes, dets, LOOSE)
        self.assertEqual(sum(x.status == "hit" for x in v), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)