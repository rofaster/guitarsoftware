import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.ir import (Detection, Note, STANDARD_TUNING,    # noqa: E402
                            midi_to_freq)
from guitarcoach.judge import LOOSE, STANDARD, judge_phrase      # noqa: E402
from guitarcoach.strings import (N_HARM, StringClassifier,       # noqa: E402
                                 assign_string, candidates_for,
                                 rank_positions, timbre_features)
from guitarcoach.synth import SR, STRING_BRIGHTNESS, pluck       # noqa: E402


def frame_of(string: int, midi: int, seed: int = 1) -> np.ndarray:
    audio = pluck(midi_to_freq(midi), 0.9, SR,
                  brightness=STRING_BRIGHTNESS[string], seed=seed)
    return audio[int(0.02 * SR):int(0.02 * SR) + 1536]


def onehot(i: int, n: int = N_HARM + 2) -> np.ndarray:
    v = np.zeros(n)
    v[i] = 1.0
    return v


class TestCandidates(unittest.TestCase):
    def test_open_low_e_is_unique(self):
        self.assertEqual(candidates_for(40), [(6, 0)])

    def test_e4_is_playable_in_several_positions(self):
        cands = candidates_for(64)
        self.assertIn((1, 0), cands)
        self.assertIn((2, 5), cands)
        self.assertIn((3, 9), cands)

    def test_out_of_range_returns_empty(self):
        self.assertEqual(candidates_for(20), [])


class TestClassifierMechanics(unittest.TestCase):
    """The classifier is exercised with controlled feature vectors.

    Audio from the synthetic guitar is NOT used to assert accuracy: its string
    model does not encode enough gauge difference to be evidence either way
    (see tools/probe_decay.py). Real accuracy has to be measured on a real
    instrument during calibration.
    """

    def build(self) -> StringClassifier:
        clf = StringClassifier(SR)
        rng = np.random.default_rng(0)
        for i, string in enumerate(sorted(STANDARD_TUNING)):
            base = onehot(i)
            for _ in range(3):
                clf.add_features(string, base + rng.normal(0, 0.05, base.size))
        return clf.fit()

    def test_learns_separable_vectors(self):
        clf = self.build()
        self.assertEqual(len(clf.centroids), 6)
        for i, string in enumerate(sorted(STANDARD_TUNING)):
            best = max(clf.centroids, key=lambda s: clf.score_features(s, onehot(i)))
            self.assertEqual(best, string)

    def test_scores_are_bounded_cosine(self):
        clf = self.build()
        s = clf.score_features(1, onehot(0))
        self.assertGreaterEqual(s, -1.0)
        self.assertLessEqual(s, 1.0 + 1e-9)

    def test_unfitted_classifier_scores_zero(self):
        clf = StringClassifier(SR)
        self.assertFalse(clf.fitted)
        self.assertEqual(clf.score_features(1, onehot(0)), 0.0)

    def test_profile_round_trip(self):
        clf = StringClassifier(SR)
        clf.add_features(1, onehot(0))
        clf.add_features(2, onehot(1))
        clf.fit()
        back = StringClassifier.from_json(clf.to_json())
        self.assertEqual(set(back.centroids), {1, 2})
        self.assertAlmostEqual(back.score_features(1, onehot(0)), 1.0, places=6)


class TestFingeringConstraint(unittest.TestCase):
    def test_hand_position_prefers_nearby_fret(self):
        ranked = rank_positions(64, np.zeros(1536), SR, None, last_fret=5)
        self.assertEqual((ranked[0].string, ranked[0].fret), (2, 5))

    def test_without_context_order_starts_at_lowest_fret(self):
        ranked = rank_positions(64, np.zeros(1536), SR, None)
        self.assertEqual(len(ranked), len(candidates_for(64)))
        self.assertEqual(ranked[0].fret, 0)

    def test_every_position_is_physically_playable(self):
        for midi in (40, 45, 52, 59, 64, 67):
            for pos in rank_positions(midi, np.zeros(1536), SR, None):
                self.assertEqual(STANDARD_TUNING[pos.string] + pos.fret, midi)


class TestAudioPathSmoke(unittest.TestCase):
    """The audio path must return a legal candidate, whatever it picks."""

    def test_returns_a_legal_position(self):
        clf = StringClassifier(SR)
        for seed in (1, 2, 3):
            clf.add_features(1, timbre_features(frame_of(1, 64, seed), SR, 64.0))
        clf.fit()
        pos = assign_string(64, frame_of(1, 64, 9), SR, clf)
        self.assertIsNotNone(pos)
        self.assertIn((pos.string, pos.fret), candidates_for(64))

    def test_feature_vector_is_unit_norm(self):
        vec = timbre_features(frame_of(3, 55), SR, 55.0)
        self.assertEqual(vec.shape[0], N_HARM + 2)
        self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=6)


class TestJudgeIntegration(unittest.TestCase):
    def setUp(self):
        self.note = Note(start=1.0, dur=0.4, midi=64, string=1, fret=0)

    def test_wrong_string_flagged_when_enabled(self):
        det = Detection(1.0, 64, cents=3.0, string=2)
        v = judge_phrase([self.note], [det], STANDARD)[0]
        self.assertEqual(v.status, "wrong_string")

    def test_loose_profile_ignores_string(self):
        det = Detection(1.0, 64, cents=3.0, string=2)
        v = judge_phrase([self.note], [det], LOOSE)[0]
        self.assertEqual(v.status, "hit")

    def test_missing_string_info_does_not_accuse(self):
        det = Detection(1.0, 64, cents=3.0, string=None)
        v = judge_phrase([self.note], [det], STANDARD)[0]
        self.assertEqual(v.status, "hit")


if __name__ == "__main__":
    unittest.main(verbosity=2)