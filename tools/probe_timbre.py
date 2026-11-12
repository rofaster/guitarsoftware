"""Diagnostic: are the synthetic strings separable by timbre features?

Prints the pitch-invariant scalars (harmonic centroid, spectral slope) per
string, at the open pitch and at a shared pitch (E4) where the string can
reach it.

    uv run --with numpy python tools/probe_timbre.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.ir import STANDARD_TUNING, midi_to_freq, note_from_string_fret  # noqa: E402
from guitarcoach.strings import timbre_features                                  # noqa: E402
from guitarcoach.synth import SR, STRING_BRIGHTNESS, pluck                       # noqa: E402


def feat(string: int, midi: int, seed: int = 7, offset: float = 0.02,
         size: int = 1536):
    audio = pluck(midi_to_freq(midi), 0.9, SR,
                  brightness=STRING_BRIGHTNESS[string], seed=seed)
    frame = audio[int(offset * SR):int(offset * SR) + size]
    v = timbre_features(frame, SR, float(midi))
    # last two entries are centroid and slope/5
    return v[-2], v[-1] * 5.0


def main() -> None:
    print("open strings (own pitch), long window @20ms:")
    print(f"{'str':>3} {'note':>4} {'bright':>6} {'centroid':>9} {'slope':>8}")
    for s, open_midi in STANDARD_TUNING.items():
        c, sl = feat(s, open_midi)
        print(f"{s:3d} {open_midi:4d} {STRING_BRIGHTNESS[s]:6.2f} {c:9.4f} {sl:8.3f}")

    print("\nE4 (64) on strings that can reach it:")
    for s in (1, 2, 3, 4):
        fret = 64 - STANDARD_TUNING[s]
        if not 0 <= fret <= 22:
            continue
        c, sl = feat(s, 64)
        c2, sl2 = feat(s, 64, offset=0.002, size=768)
        print(f"  string {s} fret {fret:2d}  bright {STRING_BRIGHTNESS[s]:.2f}"
              f"  long {c:.4f}/{sl:7.3f}   attack {c2:.4f}/{sl2:7.3f}")


if __name__ == "__main__":
    main()