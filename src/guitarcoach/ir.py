"""Score IR: tuning, note representation, conversion helpers.

All downstream modules speak this vocabulary only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Standard tuning, EADGBE: string 6 (low E) .. 1 (high E)
STANDARD_TUNING: dict[int, int] = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}

_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

DEFAULT_TEMPO = 80.0          # quarter-note BPM
DEFAULT_METER = (4, 4)
DEFAULT_BEATS_PER_BAR = 4     # legacy alias of DEFAULT_METER[0]


def midi_to_name(midi: int) -> str:
    """60 -> 'C4'."""
    return f"{_NAMES[midi % 12]}{midi // 12 - 1}"


def midi_to_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def freq_to_midi(freq: float) -> float:
    if freq <= 0:
        return float("nan")
    return 69.0 + 12.0 * math.log2(freq / 440.0)


def note_from_string_fret(string: int, fret: int,
                          tuning: dict[int, int] | None = None) -> int:
    """(string, fret) -> MIDI number."""
    tuning = tuning or STANDARD_TUNING
    return tuning[string] + fret


def fret_from_string_midi(string: int, midi: int,
                          tuning: dict[int, int] | None = None) -> int | None:
    """MIDI + string -> fret, or None if it is not a legal fingering."""
    tuning = tuning or STANDARD_TUNING
    open_midi = tuning.get(string)
    if open_midi is None:
        return None
    fret = midi - open_midi
    return fret if 0 <= fret <= 24 else None


@dataclass(frozen=True)
class Note:
    """One expected note in the score."""

    start: float          # seconds from the beginning of the exercise
    dur: float            # seconds
    midi: int
    string: int | None = None
    fret: int | None = None
    tech: str | None = None   # bend/slide/hammer/pull/vibrato/harmonic
    bar: int | None = None
    phrase_id: int | None = None

    @property
    def name(self) -> str:
        return midi_to_name(self.midi)

    @property
    def is_tech(self) -> bool:
        return self.tech is not None


@dataclass(frozen=True)
class Detection:
    """One note heard by the detector."""

    time: float           # seconds
    midi: int
    cents: float = 0.0    # deviation from the nearest semitone, -50..+50
    confidence: float = 1.0
    string: int | None = None   # 1-6, when a hex pickup (or a sim) told us
    fret: int | None = None     # 0-24, only when string + pitch give a legal fret


@dataclass
class Score:
    title: str = "untitled"
    tuning: dict[int, int] = field(default_factory=lambda: dict(STANDARD_TUNING))
    notes: list[Note] = field(default_factory=list)
    tempo: float = DEFAULT_TEMPO
    meter: tuple[int, int] = DEFAULT_METER

    @property
    def beats_per_bar(self) -> int:
        return self.meter[0]

    @property
    def beat_seconds(self) -> float:
        """One quarter note, in seconds."""
        return 60.0 / (self.tempo or DEFAULT_TEMPO)

    @property
    def bar_seconds(self) -> float:
        num, den = self.meter
        return num * (4.0 / den) * self.beat_seconds

    @property
    def duration(self) -> float:
        if not self.notes:
            return 0.0
        return max(n.start + n.dur for n in self.notes)
