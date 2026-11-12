"""Build a per-guitar string profile from six recordings.

One WAV per open string, a few seconds each (two or three plucks is plenty):

    uv run --with numpy python tools/calibrate.py --out out/string-profile.json \
        --string 6 e2.wav --string 5 a2.wav --string 4 d3.wav \
        --string 3 g3.wav --string 2 b3.wav --string 1 e4.wav

The profile is what makes string identification possible: the timbre of a
plucked string depends on the instrument, the strings and the pickup, so it
has to be learnt on the guitar that will be played.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import load_wav          # noqa: E402
from guitarcoach.detect import detect_notes        # noqa: E402
from guitarcoach.ir import STANDARD_TUNING         # noqa: E402
from guitarcoach.strings import StringClassifier   # noqa: E402


def collect(wav: Path, string: int) -> tuple[StringClassifier, int]:
    audio, sr = load_wav(wav)
    clf = StringClassifier(sr)
    open_midi = STANDARD_TUNING[string]
    dets = [d for d in detect_notes(audio, sr) if d.midi == open_midi]
    for d in dets:
        start = int((d.time + 0.02) * sr)
        frame = audio[start:start + 1536]
        if len(frame) == 1536:
            clf.add(string, frame, float(d.midi))
    return clf, len(dets)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--string", nargs=2, action="append", metavar=("N", "WAV"),
                    required=True, help="string number (1-6) and its recording")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    merged: dict[int, list] = {}
    sr = 44100
    for string_txt, wav_txt in args.string:
        string = int(string_txt)
        if string not in STANDARD_TUNING:
            raise SystemExit(f"string must be 1-6, got {string}")
        clf, used = collect(Path(wav_txt), string)
        sr = clf.sr
        if not used:
            print(f"  string {string}: no clean pluck of "
                  f"{STANDARD_TUNING[string]} found in {wav_txt}")
            continue
        merged[string] = clf.samples[string]
        print(f"  string {string}: {used} pluck(s)")

    if len(merged) < 2:
        raise SystemExit("need at least two strings calibrated")

    out = StringClassifier(sr)
    for string, vecs in merged.items():
        for v in vecs:
            out.add_features(string, v)
    out.fit()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out.to_json(), indent=2), encoding="utf-8")
    print(f"wrote {args.out} ({len(out.centroids)} strings)")


if __name__ == "__main__":
    main()