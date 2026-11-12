"""Diagnostic: does the short attack window hurt low notes?

A 1024-sample window is ~23 ms, and E2 (82 Hz) has a 12 ms period, so the low
strings are the risk. Single plucks, one note at a time.

    uv run --with numpy python tools/probe_low.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import detect_notes                    # noqa: E402
from guitarcoach.ir import midi_to_freq, midi_to_name          # noqa: E402
from guitarcoach.synth import SR, render                       # noqa: E402

SHORT = dict(attack_offset=0.005, frame_size=1024, offsets=(0.005, 0.012))
LONG = dict(attack_offset=0.020, frame_size=2048, offsets=(0.008, 0.024, 0.045))


def check(midi: int, cfg: dict):
    audio = render([(0.0, midi_to_freq(midi), 0.9, 3)], 1.1)
    dets = detect_notes(audio, SR, **cfg)
    if not dets:
        return "none", 0.0
    d = dets[0]
    return midi_to_name(d.midi), d.cents


def main() -> None:
    print(f"{'note':>6}  {'short(1024)':<20}  long(2048)")
    for midi in (40, 43, 45, 48, 50, 55, 59, 64, 67):
        s_name, s_c = check(midi, SHORT)
        l_name, l_c = check(midi, LONG)
        want = midi_to_name(midi)
        s_ok = "OK" if s_name == want else "!!"
        l_ok = "OK" if l_name == want else "!!"
        print(f"{want:>6}  {s_ok} {s_name:<4}{s_c:+6.1f}c      {l_ok} {l_name:<4}{l_c:+6.1f}c")


if __name__ == "__main__":
    main()
