"""String identification: timbre fingerprint plus fingering constraints.

Pure pitch cannot tell a note played on string 1 from the same note on string
2 — that is the "same pitch, different position" problem. Two signals break
the tie:

  1. timbre: thick and thin strings have different harmonic envelopes, learnt
     per guitar during calibration;
  2. fingering: not every position is reachable from where the hand already is.

Neither is decisive alone; the score combines them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .detect import _peak_near
from .ir import STANDARD_TUNING, midi_to_freq

MAX_FRET = 22
N_HARM = 8


def timbre_features(frame: np.ndarray, sr: int,
                    midi_float: float, n_harm: int = N_HARM) -> np.ndarray:
    """Harmonic profile of one note, normalised to unit length."""
    f0 = midi_to_freq(midi_float)
    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    bin_hz = sr / len(frame)

    mags = np.array([_peak_near(spec, bin_hz, k * f0)
                     for k in range(1, n_harm + 1)]) + 1e-9
    profile = mags / mags.sum()
    ks = np.arange(1, n_harm + 1, dtype=float)
    centroid = float((profile * ks).sum()) / n_harm
    slope = float(np.polyfit(np.log(ks), np.log(mags), 1)[0])
    vec = np.concatenate([profile, [centroid, slope / 5.0]])
    return vec / (float(np.linalg.norm(vec)) + 1e-9)


@dataclass
class StringClassifier:
    """Per-string centroids, learnt from a handful of plucks."""

    sr: int
    samples: dict[int, list[np.ndarray]] = field(
        default_factory=lambda: defaultdict(list))
    centroids: dict[int, np.ndarray] = field(default_factory=dict)

    @staticmethod
    def _unit(vec: np.ndarray) -> np.ndarray:
        return vec / (float(np.linalg.norm(vec)) + 1e-9)

    def add_features(self, string: int, vec: np.ndarray) -> None:
        """Feed a pre-computed feature vector (used by tests and offline training)."""
        self.samples[string].append(self._unit(np.asarray(vec, dtype=float)))

    def add(self, string: int, frame: np.ndarray, midi_float: float) -> None:
        self.add_features(string, timbre_features(frame, self.sr, midi_float))

    def fit(self) -> "StringClassifier":
        for string, vecs in self.samples.items():
            if vecs:
                self.centroids[string] = self._unit(np.mean(vecs, axis=0))
        return self

    @property
    def fitted(self) -> bool:
        return bool(self.centroids)

    def score_features(self, string: int, vec: np.ndarray) -> float:
        centroid = self.centroids.get(string)
        if centroid is None:
            return 0.0
        return float(np.dot(self._unit(np.asarray(vec, dtype=float)), centroid))

    def score(self, string: int, frame: np.ndarray, midi_float: float) -> float:
        return self.score_features(
            string, timbre_features(frame, self.sr, midi_float))

    # ---------------------------------------------------------------- persist
    def to_json(self) -> dict:
        return {"sr": self.sr,
                "centroids": {str(k): v.tolist() for k, v in self.centroids.items()}}

    @classmethod
    def from_json(cls, payload: dict) -> "StringClassifier":
        clf = cls(sr=int(payload.get("sr", 44100)))
        clf.centroids = {int(k): np.asarray(v, dtype=float)
                         for k, v in payload.get("centroids", {}).items()}
        return clf


def candidates_for(midi: int,
                   tuning: dict[int, int] | None = None) -> list[tuple[int, int]]:
    """Every (string, fret) that can produce this pitch."""
    tuning = tuning or STANDARD_TUNING
    out = []
    for string, open_midi in sorted(tuning.items()):
        fret = midi - open_midi
        if 0 <= fret <= MAX_FRET:
            out.append((string, fret))
    return out


@dataclass(frozen=True)
class Position:
    string: int
    fret: int
    score: float


def rank_positions(midi: int, frame: np.ndarray, sr: int,
                   clf: StringClassifier | None = None,
                   last_fret: int | None = None,
                   hand_span: int = 4,
                   tuning: dict[int, int] | None = None) -> list[Position]:
    """Order the playable positions for this note, best first."""
    cands = candidates_for(midi, tuning)
    if not cands:
        return []

    out: list[Position] = []
    for string, fret in cands:
        timbre = 0.0
        if clf is not None and clf.fitted:
            timbre = clf.score(string, frame, float(midi))
        penalty = 0.0
        if last_fret is not None:
            penalty = max(0, abs(fret - last_fret) - hand_span) * 0.08
        out.append(Position(string, fret, timbre - penalty))
    return sorted(out, key=lambda p: p.score, reverse=True)


def assign_string(midi: int, frame: np.ndarray, sr: int,
                  clf: StringClassifier | None = None,
                  last_fret: int | None = None) -> Position | None:
    ranked = rank_positions(midi, frame, sr, clf, last_fret)
    return ranked[0] if ranked else None