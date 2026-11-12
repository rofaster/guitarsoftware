"""Score validation at load time: flag, never modify.

Rules come from docs/v1-music-spec.md ("谱面校验"). Every problem becomes an
Issue that the UI paints yellow; nothing here deletes or rewrites a note.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .ir import Score

MIDI_LOW, MIDI_HIGH = 40, 88          # E2..E6, 24-fret standard guitar
EPS = 1e-6
FOLLOW_TECH = {"slide", "hammer", "pull"}   # may legitimately overlap the previous note

RANGE = "超出常用音域"
POSITION = "弦或品位非法"
MISMATCH = "弦品与音高不一致"
TIMING = "起点或时值非法"
ORDER = "音符未按起点排序"
BAR_CLOSE = "小节时值不闭合"
TIE = "跨小节延音"
SAME_STRING = "同弦时值冲突"


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    index: int | None = None     # note index, when it is about one note
    bar: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def validate_score(score: Score) -> list[Issue]:
    issues: list[Issue] = []
    notes = score.notes
    beat = score.beat_seconds
    bar_len = score.bar_seconds
    tol = beat / 32.0

    for i, n in enumerate(notes):
        if not (MIDI_LOW <= n.midi <= MIDI_HIGH):
            issues.append(Issue("range", f"{RANGE}（MIDI {n.midi}）", i, n.bar))
        bad_pos = ((n.string is not None and not 1 <= n.string <= 6)
                   or (n.fret is not None and not 0 <= n.fret <= 24))
        if bad_pos:
            issues.append(Issue("position", POSITION, i, n.bar))
        elif n.string is not None and n.fret is not None:
            open_midi = score.tuning.get(n.string)
            if open_midi is not None and open_midi + n.fret != n.midi:
                issues.append(Issue("mismatch",
                                    f"{MISMATCH}（{n.string} 弦 {n.fret} 品 ≠ MIDI {n.midi}）",
                                    i, n.bar))
        if n.start < 0 or n.dur <= 0:
            issues.append(Issue("timing", TIMING, i, n.bar))
        if i > 0 and n.start < notes[i - 1].start - EPS:
            issues.append(Issue("order", ORDER, i, n.bar))

    if bar_len <= 0:
        return issues

    # tails crossing a bar line
    for i, n in enumerate(notes):
        if n.dur <= 0:
            continue
        bar_idx = int(n.start // bar_len + 1e-9)
        bar_end = (bar_idx + 1) * bar_len
        if n.start + n.dur > bar_end + tol:
            issues.append(Issue("tie", TIE, i, n.bar))

    # same-string overlaps
    last_on_string: dict[int, int] = {}
    for i, n in enumerate(notes):
        if n.string is None:
            continue
        j = last_on_string.get(n.string)
        if j is not None:
            prev = notes[j]
            if prev.start + prev.dur > n.start + tol and n.tech not in FOLLOW_TECH:
                issues.append(Issue("same_string", SAME_STRING, i, n.bar))
        last_on_string[n.string] = i

    # bar closure: notes + rests must fill each bar exactly (±1/32 beat).
    # Notes are clipped to the bar; overlaps make the sum overshoot.
    if notes:
        last_bar = int(max(n.start for n in notes) // bar_len + 1e-9)
        for b in range(last_bar + 1):
            lo, hi = b * bar_len, (b + 1) * bar_len
            spans = sorted((max(n.start, lo), min(n.start + n.dur, hi))
                           for n in notes if n.dur > 0
                           and n.start < hi - EPS and n.start + n.dur > lo + EPS)
            occupied = sum(e - s for s, e in spans)
            rests, cursor = 0.0, lo
            for s, e in spans:
                if s > cursor:
                    rests += s - cursor
                cursor = max(cursor, e)
            rests += max(0.0, hi - cursor)
            if abs(occupied + rests - bar_len) > tol:
                issues.append(Issue("bar_close",
                                    f"{BAR_CLOSE}（第 {b + 1} 小节）", None, b))

    # bar marks that disagree with the timing
    for i, n in enumerate(notes):
        if n.bar is not None and n.start >= 0:
            expected = int(n.start // bar_len + 1e-9)
            if n.bar != expected:
                issues.append(Issue("bar_mark",
                                    f"{BAR_CLOSE}（标在第 {n.bar + 1} 小节，按时间应在第 {expected + 1} 小节）",
                                    i, n.bar))
    return issues
