"""Command line entry points.

  python -m guitarcoach.cli                       # two synthetic takes
  python -m guitarcoach.cli --verbose             # ... with detected onsets
  python -m guitarcoach.cli --save-demo out/      # write score.json + take.wav
  python -m guitarcoach.cli --wav out/take.wav --score out/score.json
  python -m guitarcoach.cli --device bluetooth    # judging strategy for a device
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .audio_io import load_wav, save_wav
from .detect import detect_notes
from .exercises import builtin_score
from .input import choose_profile
from .ir import midi_to_freq, midi_to_name
from .judge import LOOSE, STANDARD, STRICT, judge_phrase, report
from .score_io import load_score, save_score
from .synth import SR, render

DEVICES = {
    "interface": dict(driver="asio", latency_ms=12.0, channels=2),
    "usb-mic": dict(driver="wasapi", latency_ms=28.0, channels=1),
    "builtin-mic": dict(driver="wasapi", latency_ms=55.0, channels=1,
                        sample_rate=48000),
    "bluetooth": dict(driver="wasapi", is_bluetooth=True, latency_ms=180.0),
    "midi": dict(driver="asio", has_midi=True, latency_ms=4.0),
}


def build_score():
    return builtin_score()


def build_take(notes, rng, *, timing_sd, detune_sd,
               sharp_index=None, sharp_cents=0.0,
               late_index=None, late_s=0.0):
    events = []
    for i, n in enumerate(notes):
        when = n.start + rng.normal(0, timing_sd)
        detune = rng.normal(0, detune_sd)
        if i == sharp_index:
            detune += sharp_cents
        if i == late_index:
            when += late_s
        events.append((max(0.0, when), midi_to_freq(n.midi + detune / 100.0),
                       0.55, i))
    return render(events, notes[-1].start + 1.4)


def show(name: str, audio, notes, verbose: bool = False) -> None:
    dets = detect_notes(audio, SR)
    print("=" * 68)
    print(f"take: {name}    ({len(audio)/SR:.2f} s, {len(dets)} onsets detected)")
    print("  expected: " + "  ".join(n.name for n in notes))
    if verbose:
        for d in dets:
            print(f"    heard {d.time:5.2f}s {midi_to_name(d.midi):>4} "
                  f"{d.cents:+6.1f}c conf {d.confidence:.2f}")
    print("-" * 68)
    for profile in (LOOSE, STANDARD, STRICT):
        print(report(judge_phrase(notes, dets, profile), profile))
        print()


def run_file_mode(wav: Path, score_path: Path, verbose: bool) -> None:
    audio, sr = load_wav(wav)
    score = load_score(score_path)
    print(f"wav   : {wav}  ({len(audio)/sr:.2f} s @ {sr} Hz)")
    print(f"score : {score.title}  ({len(score.notes)} notes)")
    dets = detect_notes(audio, sr)
    print(f"onsets: {len(dets)}")
    if verbose:
        for d in dets:
            print(f"    heard {d.time:5.2f}s {midi_to_name(d.midi):>4} "
                  f"{d.cents:+6.1f}c conf {d.confidence:.2f}")
    print()
    print(report(judge_phrase(score.notes, dets, LOOSE), LOOSE))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="guitarcoach")
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--score", type=Path)
    ap.add_argument("--save-demo", type=Path, metavar="DIR")
    ap.add_argument("--device", choices=sorted(DEVICES))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.device:
        profile = choose_profile(**DEVICES[args.device])
        print(json.dumps({"device": args.device,
                          "profile": profile.describe(),
                          "warning_code": profile.warning_code,
                          "warning": profile.warning},
                         ensure_ascii=True, indent=2))
        return

    if args.wav and args.score:
        run_file_mode(args.wav, args.score, args.verbose)
        return

    score = build_score()

    if args.save_demo:
        out = args.save_demo
        out.mkdir(parents=True, exist_ok=True)
        save_score(score, out / "score.json")
        take = build_take(score.notes, np.random.default_rng(7),
                          timing_sd=0.015, detune_sd=8.0,
                          sharp_index=4, sharp_cents=120.0,
                          late_index=7, late_s=0.50)
        save_wav(out / "take.wav", take, SR)
        print(f"wrote {out/'score.json'} and {out/'take.wav'}")
        print(f"now run: --wav {out/'take.wav'} --score {out/'score.json'}")
        return

    print(f"score: {score.title}  {len(score.notes)} notes, "
          f"{score.tempo:.0f} BPM, default 0.7x")
    audio_a = build_take(score.notes, np.random.default_rng(7),
                         timing_sd=0.015, detune_sd=8.0,
                         sharp_index=4, sharp_cents=120.0,
                         late_index=7, late_s=0.50)
    show("A competent, one sharp note, one 500 ms late", audio_a, score.notes,
         args.verbose)

    audio_b = build_take(score.notes, np.random.default_rng(3),
                         timing_sd=0.160, detune_sd=40.0,
                         sharp_index=6, sharp_cents=60.0)
    show("B beginner, +-160 ms timing, tuning drift", audio_b, score.notes,
         args.verbose)


if __name__ == "__main__":
    main()
