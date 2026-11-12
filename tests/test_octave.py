import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import detect_notes, harmonic_ratio   # noqa: E402
from guitarcoach.ir import midi_to_freq, midi_to_name         # noqa: E402
from guitarcoach.synth import SR, pluck, render               # noqa: E402


class TestOctaveHandling(unittest.TestCase):
    """The failure this guards against: an octave-down estimate when the
    previous string is still ringing.

    Boundary measured with tools/probe_overlap.py: two notes 250 ms apart or
    more are resolved correctly; at 150 ms and below the monophonic estimator
    reports a third pitch (the composite period), which is a documented
    limitation, not a regression.
    """

    def test_two_overlapping_notes_keep_their_octave(self):
        events = [(0.00, midi_to_freq(55), 0.90, 1),   # G3
                  (0.25, midi_to_freq(59), 0.90, 2)]   # B3, 250 ms later
        audio = render(events, 1.4)
        dets = detect_notes(audio, SR)
        midis = [d.midi for d in dets]
        self.assertIn(55, midis, f"G3 lost, heard {[midi_to_name(m) for m in midis]}")
        self.assertIn(59, midis, f"B3 lost, heard {[midi_to_name(m) for m in midis]}")

    def test_overlap_does_not_add_octave_ghosts(self):
        events = [(0.00, midi_to_freq(55), 0.90, 1),
                  (0.25, midi_to_freq(59), 0.90, 2)]
        audio = render(events, 1.4)
        dets = detect_notes(audio, SR)
        wrong = [d for d in dets if d.midi not in (55, 59)]
        self.assertFalse(wrong, f"ghosts: {[midi_to_name(d.midi) for d in wrong]}")

    def test_single_pluck_is_exact(self):
        audio = render([(0.0, midi_to_freq(64), 0.8, 9)], 1.0)
        dets = detect_notes(audio, SR)
        self.assertTrue(dets)
        self.assertEqual(dets[0].midi, 64)          # E4
        self.assertLess(abs(dets[0].cents), 15)

    def test_harmonic_ratio_prefers_true_f0(self):
        audio = render([(0.0, midi_to_freq(57), 0.6, 4)], 0.8)
        frame = audio[int(0.03 * SR):int(0.03 * SR) + 1536]
        spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
        bin_hz = SR / len(frame)
        f0 = float(midi_to_freq(57))
        self.assertGreater(harmonic_ratio(spec, bin_hz, f0),
                           harmonic_ratio(spec, bin_hz, f0 / 2))
        self.assertGreater(harmonic_ratio(spec, bin_hz, f0),
                           harmonic_ratio(spec, bin_hz, f0 * 2))


class TestPluckTuning(unittest.TestCase):
    def test_karplus_strong_lands_on_pitch(self):
        for midi in (40, 45, 55, 64):
            audio = pluck(midi_to_freq(midi), 0.5, seed=5)
            frame = audio[int(0.05 * SR):int(0.05 * SR) + 2048]
            from guitarcoach.detect import yin_pitch
            f0 = yin_pitch(frame, SR)
            self.assertGreater(f0, 0)
            cents = 1200 * np.log2(f0 / midi_to_freq(midi))
            self.assertLess(abs(cents), 25, f"midi {midi} off by {cents:.1f} cents")


if __name__ == "__main__":
    unittest.main(verbosity=2)