"""Diagnostic: does per-harmonic decay separate the strings?

A static spectrum is ambiguous because the loop filter settles within ~20 ms.
What actually differs between a thick and a thin string is how fast each
partial dies away, so this prints the late/early magnitude ratio per harmonic.

    uv run --with numpy python tools/probe_decay.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import _peak_near                        # noqa: E402
from guitarcoach.ir import STANDARD_TUNING, midi_to_freq         # noqa: E402
from guitarcoach.synth import SR, STRING_BRIGHTNESS, pluck       # noqa: E402


def harmonics(frame: np.ndarray, midi: int, n_harm: int = 6) -> np.ndarray:
    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    bin_hz = SR / len(frame)
    f0 = midi_to_freq(midi)
    return np.array([_peak_near(spec, bin_hz, k * f0) for k in range(1, n_harm + 1)]) + 1e-12


def decay_ratios(string: int, midi: int, seed: int = 5) -> np.ndarray:
    audio = pluck(midi_to_freq(midi), 1.2, SR,
                  brightness=STRING_BRIGHTNESS[string], seed=seed)
    early = audio[int(0.020 * SR):int(0.020 * SR) + 1536]
    late = audio[int(0.300 * SR):int(0.300 * SR) + 768]
    return harmonics(late, midi, 5) / harmonics(early, midi, 5)


def main() -> None:
    print("late/early magnitude per harmonic, E4 (64) on each reachable string")
    print(f"{'string':>6} {'fret':>4} {'bright':>6}   " +
          "  ".join(f"h{k}" for k in range(1, 6)))
    rows = []
    for s in (1, 2, 3, 4, 5, 6):
        fret = 64 - STANDARD_TUNING[s]
        if not 0 <= fret <= 22:
            continue
        r = decay_ratios(s, 64)
        rows.append((s, r))
        print(f"{s:6d} {fret:4d} {STRING_BRIGHTNESS[s]:6.2f}   " +
              "  ".join(f"{v:5.2f}" for v in r))

    if len(rows) >= 2:
        spread = np.max([r for _, r in rows], axis=0) - np.min([r for _, r in rows], axis=0)
        print("\nspread per harmonic:", "  ".join(f"{v:5.2f}" for v in spread))


if __name__ == "__main__":
    main()