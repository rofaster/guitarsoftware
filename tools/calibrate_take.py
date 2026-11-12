"""Calibrate the six open strings from one continuous take.

The take is expected to be the six open strings, low to high, one pluck each.
Onsets are taken from the detector but the *pitch* comes from the tuning order:
calibration knows which string was played, so a misread note must not poison
the profile.

    uv run --with numpy python tools/calibrate_take.py out/recordings/raw.wav \
        --out out/string-profile.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import load_wav                 # noqa: E402
from guitarcoach.detect import detect_notes              # noqa: E402
from guitarcoach.ir import STANDARD_TUNING, midi_to_name  # noqa: E402
from guitarcoach.strings import StringClassifier, timbre_features  # noqa: E402

FRAME = 1536
OFFSET = 0.02


def similarity_matrix(clf: StringClassifier) -> tuple[list[int], np.ndarray]:
    strings = sorted(clf.centroids)
    mat = np.zeros((len(strings), len(strings)))
    for i, a in enumerate(strings):
        for j, b in enumerate(strings):
            mat[i, j] = float(np.dot(clf.centroids[a], clf.centroids[b]))
    return strings, mat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/string-profile.json"))
    ap.add_argument("--min-confidence", type=float, default=0.45,
                    help="drop quiet onsets (ringing harmonics, room noise)")
    args = ap.parse_args()

    audio, sr = load_wav(args.wav)
    dets = [d for d in detect_notes(audio, sr) if d.confidence >= args.min_confidence]
    dets.sort(key=lambda d: d.time)

    expected = [STANDARD_TUNING[s] for s in sorted(STANDARD_TUNING, reverse=True)]
    print(f"{args.wav.name}: {len(audio)/sr:.1f} s, {len(dets)} confident onsets")
    if len(dets) != len(expected):
        print(f"  expected {len(expected)} (six open strings), got {len(dets)}")
        print("  onsets:", ", ".join(f"{d.time:.2f}s/{midi_to_name(d.midi)}"
                                     for d in dets))
        raise SystemExit("re-record with one clean pluck per string, or raise --min-confidence")

    clf = StringClassifier(sr)
    print(f"\n{'string':>6} {'expected':>9} {'heard':>7} {'cents':>7} {'frame':>9}")
    for string, midi, det in zip(sorted(STANDARD_TUNING, reverse=True), expected, dets):
        start = int(det.time * sr + OFFSET * sr)
        frame = audio[start:start + FRAME]
        if len(frame) < FRAME:
            continue
        clf.add(string, frame, float(midi))
        cents = (det.midi - midi) * 100 + det.cents
        print(f"{string:6d} {midi_to_name(midi):>9} {midi_to_name(det.midi):>7} "
              f"{cents:+7.1f} {len(frame):9d}")

    clf.fit()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(clf.to_json(), indent=2), encoding="utf-8")

    strings, mat = similarity_matrix(clf)
    print("\ncosine similarity between the six string templates:")
    print("       " + "".join(f"{s:>8}" for s in strings))
    for i, s in enumerate(strings):
        row = "".join(f"{mat[i, j]:8.2f}" for j in range(len(strings)))
        print(f"  {s:>3}  {row}")

    off_diag = [mat[i, j] for i in range(len(strings)) for j in range(len(strings)) if i != j]
    print(f"\nmean off-diagonal similarity: {np.mean(off_diag):.3f} "
          f"(lower = strings more distinct)")
    print(f"profile written: {args.out}")


if __name__ == "__main__":
    main()