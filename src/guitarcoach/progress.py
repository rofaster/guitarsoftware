"""Practice navigation.

The unit of seeking is the bar (spec: "基本单位是小节"). Phrase marks are kept
on every note for display and future phrase-level features.
Scores without bar marks are cut every bar of the score's meter (default 4/4);
scores without phrase marks are split every 8 beats.
"""

from __future__ import annotations

from .ir import DEFAULT_METER, DEFAULT_TEMPO, Note, Score

# Auto-split fallback when the score has no phrase marks.
BEATS_PER_PHRASE = 8


def beat_duration(tempo: float | None) -> float:
    return 60.0 / (tempo or DEFAULT_TEMPO)


def annotate_score(score: Score) -> Score:
    """Fill in bar / phrase_id when they are missing. Existing marks are kept."""
    tempo = score.tempo or DEFAULT_TEMPO
    meter = tuple(score.meter or DEFAULT_METER)
    sized = Score(title=score.title, tempo=tempo, meter=meter)
    bar_len = sized.bar_seconds
    phrase_len = BEATS_PER_PHRASE * beat_duration(tempo)
    has_phrases = any(n.phrase_id is not None for n in score.notes)
    notes: list[Note] = []
    for n in score.notes:
        bar = n.bar
        if bar is None:
            bar = int(n.start // bar_len + 1e-9) if bar_len > 0 else 0
        if has_phrases:
            pid = 0 if n.phrase_id is None else n.phrase_id
        else:
            pid = int(n.start // phrase_len) if phrase_len > 0 else 0
        notes.append(Note(start=n.start, dur=n.dur, midi=n.midi,
                          string=n.string, fret=n.fret, tech=n.tech,
                          bar=bar, phrase_id=pid))
    return Score(title=score.title, tuning=dict(score.tuning), notes=notes,
                 tempo=tempo, meter=meter)


# ---------- bars ----------

def bar_start(notes: list[Note], index: int) -> int:
    """Index of the first note in the bar that contains `index`."""
    if not notes:
        return 0
    index = min(max(index, 0), len(notes) - 1)
    bar = notes[index].bar
    i = index
    while i > 0 and notes[i - 1].bar == bar:
        i -= 1
    return i


def prev_bar_start(notes: list[Note], index: int) -> int:
    """Start of the bar before the one holding `index` (or this bar if first)."""
    if not notes:
        return 0
    start = bar_start(notes, min(index, len(notes) - 1))
    if start == 0:
        return 0
    return bar_start(notes, start - 1)


def rewind(notes: list[Note], index: int) -> int:
    """Back: current bar start, or the previous bar if already there."""
    if not notes:
        return 0
    if index >= len(notes):
        return bar_start(notes, len(notes) - 1)
    index = max(0, index)
    start = bar_start(notes, index)
    if index > start:
        return start
    return prev_bar_start(notes, start)


def advance(notes: list[Note], index: int) -> tuple[int, list[int]]:
    """Jump to the next bar start. Returns (destination, skipped indices)."""
    if not notes:
        return 0, []
    index = min(max(index, 0), len(notes))
    if index >= len(notes):
        return len(notes), []
    bar = notes[index].bar
    dest = index
    while dest < len(notes) and notes[dest].bar == bar:
        dest += 1
    return dest, list(range(index, dest))


def first_index_of_bar(notes: list[Note], bar: int) -> int:
    """First note at or after `bar` (len(notes) when none)."""
    for i, n in enumerate(notes):
        if n.bar is not None and n.bar >= bar:
            return i
    return len(notes)


def last_index_of_bar(notes: list[Note], bar: int) -> int:
    """Last note at or before `bar` (-1 when none)."""
    last = -1
    for i, n in enumerate(notes):
        if n.bar is not None and n.bar <= bar:
            last = i
    return last


def snap_to_bar(notes: list[Note], time: float) -> int:
    """Scrub bar: index of the bar-start note closest to `time`."""
    if not notes:
        return 0
    starts = [i for i in range(len(notes)) if i == 0 or notes[i].bar != notes[i - 1].bar]
    return min(starts, key=lambda i: abs(notes[i].start - time))


# ---------- phrases (kept for display / later use) ----------

def phrase_start(notes: list[Note], index: int) -> int:
    if not notes:
        return 0
    index = min(max(index, 0), len(notes) - 1)
    pid = notes[index].phrase_id
    i = index
    while i > 0 and notes[i - 1].phrase_id == pid:
        i -= 1
    return i


def snap_to_note(notes: list[Note], time: float) -> int:
    if not notes:
        return 0
    return min(range(len(notes)), key=lambda i: abs(notes[i].start - time))
