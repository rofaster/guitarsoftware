"""Built-in practice scores. The first exercise does not depend on tab search.

Default is 空弦练习 (scores/open-strings.json). The G-string run is kept as
the next exercise, via g_string_run().
"""

from __future__ import annotations

from .ir import Note, Score, note_from_string_fret

TEMPO = 80.0
BEAT = 60.0 / TEMPO

# Open-string walk, matching scores/open-strings.json:
# bars 1-2 go 6→1, bars 3-4 walk back, all fret 0, two phrases.
_OPEN = [6, 5, 4, 3, 2, 1, 1, 2, 1, 2, 3, 4, 5, 6, 6, 5]


def _quarters(fingerings: list[tuple[int, int]], title: str) -> Score:
    notes = []
    for i, (string, fret) in enumerate(fingerings):
        bar = i // 4
        notes.append(Note(
            start=i * BEAT,
            dur=BEAT,
            midi=note_from_string_fret(string, fret),
            string=string,
            fret=fret,
            bar=bar,
            phrase_id=bar // 2,
        ))
    return Score(title=title, tempo=TEMPO, meter=(4, 4), notes=notes)


def open_strings_score() -> Score:
    """空弦练习: 6th string to 1st and back, 80 BPM, 4 bars, 2 phrases."""
    return _quarters([(s, 0) for s in _OPEN], "空弦练习")


def g_string_run() -> Score:
    """G 弦音阶走句: kept as the next built-in exercise, not the v1 default."""
    up = [(3, 0), (3, 2), (3, 4), (3, 5), (3, 7), (3, 9), (3, 10), (3, 12)]
    return _quarters(up + list(reversed(up)), "G 弦音阶走句")


def builtin_score() -> Score:
    return open_strings_score()
