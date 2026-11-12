"""List what the detector hears in a recording.

    uv run --with numpy python tools/analyze_recording.py out/recordings/raw.wav
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import load_wav           # noqa: E402
from guitarcoach.detect import detect_notes         # noqa: E402
from guitarcoach.ir import STANDARD_TUNING, midi_to_name, note_from_string_fret  # noqa: E402

OPEN = {midi: string for string, midi in STANDARD_TUNING.items()}


def main() -> None:
    path = Path(sys.argv[1])
    audio, sr = load_wav(path)
    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"{path.name}: {len(audio)/sr:.2f} s @ {sr} Hz, rms {rms:.3f}, "
          f"peak {float(np.max(np.abs(audio))):.3f}")

    dets = detect_notes(audio, sr)
    print(f"\ndetected {len(dets)} onsets:")
    print(f"{'#':>2} {'time':>7} {'note':>5} {'cents':>7} {'conf':>5}  open string?")
    for i, d in enumerate(dets):
        open_string = OPEN.get(d.midi)
        tag = f"string {open_string} open" if open_string else ""
        print(f"{i:2d} {d.time:7.2f} {midi_to_name(d.midi):>5} "
              f"{d.cents:+7.1f} {d.confidence:5.2f}  {tag}")

    if dets:
        gaps = np.diff([d.time for d in dets])
        print(f"\nmedian gap between onsets: {np.median(gaps):.2f} s")


if __name__ == "__main__":
    main()