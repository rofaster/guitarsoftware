"""Hexaphonic input: one channel per string.

A 6-channel WAV or an in-memory ArraySource stands in for an external
hexaphonic pickup, so the fretboard can show where the player actually
pressed without any hardware attached.

Channel map (0-based WAV / array column -> guitar string number):
  0 -> 1 (high E), 1 -> 2 (B), 2 -> 3 (G),
  3 -> 4 (D),      4 -> 5 (A), 5 -> 6 (low E)

The detector on each channel is independent. The resulting Detection carries
`string` always, and `fret` when pitch + string is a legal fingering.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .audio_input import HEX_CHANNELS, ArraySource
from .ir import (STANDARD_TUNING, Detection, Score, fret_from_string_midi,
                 midi_to_freq)
from .live import StreamDetector
from .synth import STRING_BRIGHTNESS, SR, pluck

# WAV channel i -> string number
CHANNEL_TO_STRING = tuple(range(1, HEX_CHANNELS + 1))


def tag_fingering(det: Detection, tuning: dict[int, int] | None = None) -> Detection:
    """Fill in fret from string + midi when it is a legal position."""
    if det.string is None:
        return det
    fret = fret_from_string_midi(det.string, det.midi, tuning)
    if fret == det.fret:
        return det
    return Detection(time=det.time, midi=det.midi, cents=det.cents,
                     confidence=det.confidence, string=det.string, fret=fret)


class HexStreamDetector:
    """Six independent stream detectors, one per string channel."""

    def __init__(self, sr: int, tuning: dict[int, int] | None = None, **kw):
        self.sr = sr
        self.tuning = tuning or dict(STANDARD_TUNING)
        self._dets = [StreamDetector(sr, **kw) for _ in range(HEX_CHANNELS)]

    @property
    def total(self) -> int:
        return self._dets[0].total

    def push(self, block: np.ndarray) -> list[Detection]:
        b = np.asarray(block, dtype=np.float64)
        if b.ndim == 1:
            # mono fallback: pitch only, no string
            return [tag_fingering(d, self.tuning) for d in self._dets[0].push(b)]
        if b.shape[1] < HEX_CHANNELS:
            raise ValueError(f"hex block needs {HEX_CHANNELS} channels, got {b.shape}")
        out: list[Detection] = []
        for ch in range(HEX_CHANNELS):
            string = CHANNEL_TO_STRING[ch]
            for d in self._dets[ch].push(b[:, ch]):
                out.append(tag_fingering(
                    Detection(time=d.time, midi=d.midi, cents=d.cents,
                              confidence=d.confidence, string=string),
                    self.tuning))
        out.sort(key=lambda d: (d.time, d.string or 0))
        return out


@dataclass(frozen=True)
class HexPluck:
    """One note in a simulated hex take: sounded on `string` at `midi`."""

    start: float
    midi: int
    string: int
    dur: float = 0.5
    seed: int | None = None


def string_overrides(score: Score, shift: int) -> dict[int, int]:
    """Same pitch, moved `shift` strings toward string 1 (positive) or 6.

    Notes that would leave the board or need a negative fret are omitted,
    so the caller can leave those notes on the written string.
    """
    overrides: dict[int, int] = {}
    if not shift:
        return overrides
    for i, n in enumerate(score.notes):
        written = n.string if n.string is not None else 3
        played = written - shift
        if 1 <= played <= 6 and fret_from_string_midi(played, n.midi) is not None:
            overrides[i] = played
    return overrides


def plucks_from_score(score: Score,
                      string_of: dict[int, int] | None = None) -> list[HexPluck]:
    """Build a hex take from a score. `string_of[index]` overrides the written string."""
    out = []
    for i, n in enumerate(score.notes):
        string = (string_of or {}).get(i, n.string)
        if string is None:
            string = 3
        out.append(HexPluck(start=n.start, midi=n.midi, string=string, dur=n.dur, seed=i))
    return out


def render_hex(plucks: list[HexPluck], total: float, sr: int = SR) -> np.ndarray:
    """Render a 6-channel take, one string per column. Peak-normalised per file."""
    n = int(total * sr)
    mix = np.zeros((n, HEX_CHANNELS))
    for i, p in enumerate(plucks):
        if not 1 <= p.string <= HEX_CHANNELS:
            raise ValueError(f"string must be 1-6, got {p.string}")
        brightness = STRING_BRIGHTNESS.get(p.string, 1.0)
        sig = pluck(midi_to_freq(p.midi), p.dur, sr,
                    brightness=brightness, seed=p.seed if p.seed is not None else i)
        ch = p.string - 1
        a = int(p.start * sr)
        b = min(n, a + len(sig))
        if a < n:
            mix[a:b, ch] += sig[: b - a]
    peak = float(np.max(np.abs(mix))) or 1.0
    return mix / peak * 0.9


def hex_source(plucks: list[HexPluck], total: float, sr: int = SR,
               block_ms: float = 20.0) -> ArraySource:
    """In-memory hex source: no file, no hardware."""
    return ArraySource(render_hex(plucks, total, sr), sr, block_ms=block_ms)


def main(argv: list[str] | None = None) -> None:
    """Write a 6-channel WAV from a score, for UI and pipeline tests."""
    import argparse
    from pathlib import Path

    from .audio_io import save_wav
    from .exercises import builtin_score
    from .score_io import load_score

    ap = argparse.ArgumentParser(
        prog="guitarcoach.hex",
        description="Render a 6-channel (hexaphonic) WAV from a score. "
                    "Channel 0 = string 1 (high E), channel 5 = string 6 (low E).")
    ap.add_argument("--score", type=Path, help="JSON score; default: built-in open-string exercise")
    ap.add_argument("--out", type=Path, required=True, help="output WAV path")
    ap.add_argument("--shift-string", type=int, default=0,
                    help="same pitch, this many strings toward string 1 "
                         "(positive) or string 6 (negative). Open notes "
                         "cannot move to a thinner string (negative fret), "
                         "so use -1 for the built-in open-string exercise; "
                         "string 6 is left as-is. Impossible fingerings "
                         "are skipped.")
    args = ap.parse_args(argv)

    score = load_score(args.score) if args.score else builtin_score()
    overrides = string_overrides(score, args.shift_string)
    if args.shift_string and not overrides:
        print("warning: --shift-string "
              f"{args.shift_string} left every note unchanged "
              "(open notes need a thicker string, e.g. -1)")
    plucks = plucks_from_score(score, overrides or None)
    end = (max(p.start + p.dur for p in plucks) + 0.5) if plucks else 1.0
    save_wav(args.out, render_hex(plucks, end), SR)
    shifted = len(overrides)
    print(f"wrote {args.out}  ({len(plucks)} notes, "
          f"{shifted} shifted, 6 channels, {SR} Hz)")


if __name__ == "__main__":
    main()
