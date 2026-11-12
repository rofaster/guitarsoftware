"""Diagnostic: does hugging the attack transient help when two notes overlap?

The adaptive-window idea (shrink the window based on the gap to the next
onset) changed nothing, which says the contamination comes from the PREVIOUS
note's tail, not from the window running into the next one. This probe tests
the other hypothesis: at the attack instant the new pluck is far louder than
the old note's decay, so a very short window right on the onset may work.

    uv run --with numpy python tools/probe_attack.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.detect import detect_notes                    # noqa: E402
from guitarcoach.ir import midi_to_freq, midi_to_name          # noqa: E402
from guitarcoach.synth import SR, render                       # noqa: E402

TARGET = [55, 59]
CONFIGS = [
    ("default", dict()),
    ("attack+0/512", dict(attack_offset=0.0, frame_size=512, offsets=(0.0,))),
    ("attack+2/768", dict(attack_offset=0.002, frame_size=768, offsets=(0.002, 0.006))),
    ("attack+5/1024", dict(attack_offset=0.005, frame_size=1024, offsets=(0.005, 0.012))),
    ("attack+0/768x3", dict(attack_offset=0.0, frame_size=768, offsets=(0.0, 0.006, 0.012))),
]


def run(gap: float, cfg: dict):
    events = [(0.0, midi_to_freq(55), 0.90, 1), (gap, midi_to_freq(59), 0.90, 2)]
    dets = detect_notes(render(events, 1.5), SR, **cfg)
    ids = [d.midi for d in dets]
    return ids, " ".join(midi_to_name(m) for m in ids)


def main() -> None:
    for gap in (0.10, 0.15, 0.20):
        print(f"\n--- gap {gap:.2f}s  (want G3 B3) ---")
        for name, cfg in CONFIGS:
            ids, txt = run(gap, cfg)
            print(f"  {name:<15} {'OK' if ids == TARGET else '!!'}  {txt}")


if __name__ == "__main__":
    main()
