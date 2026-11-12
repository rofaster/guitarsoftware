"""Diagnostic: how close can two notes be before the estimator fails?

    uv run --with numpy python tools/probe_overlap.py

Result (2026-11): 0.08-0.15 s are not separable; 0.20 s and above are. This
boundary is set by the previous note's decay, not by the analysis window, so
adaptive windows do not move it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import detect_notes                    # noqa: E402
from guitarcoach.ir import midi_to_freq, midi_to_name          # noqa: E402
from guitarcoach.synth import SR, render                       # noqa: E402

TARGET = [55, 59]          # G3 then B3


def main() -> None:
    print(f"{'gap(s)':>8}  result")
    for gap in (0.08, 0.10, 0.15, 0.20, 0.25, 0.35):
        events = [(0.0, midi_to_freq(55), 0.90, 1),
                  (gap, midi_to_freq(59), 0.90, 2)]
        dets = detect_notes(render(events, 1.5), SR)
        ids = [d.midi for d in dets]
        txt = " ".join(f"{d.time:.2f}s {midi_to_name(d.midi)}" for d in dets)
        print(f"{gap:8.2f}  {'OK' if ids == TARGET else '!!'}  {txt}")


if __name__ == "__main__":
    main()