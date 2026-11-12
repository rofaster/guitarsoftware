"""Length-aware judging.

The default profile is LOOSE: never interrupt the player, never accuse them
of a wrong string, and prefer a missed note over a false accusation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ir import Detection, Note


@dataclass(frozen=True)
class JudgeConfig:
    pitch_tolerance_cents: float = 80.0
    window_before: float = 0.200      # note may arrive up to 200 ms early
    window_after: float = 0.350       # ... or 350 ms late
    judge_string: bool = False        # string position is a hint, not a score
    judge_onset: bool = True          # False for bluetooth / degraded input
    ignore_tech: bool = True          # bends, slides, harmonics pass for free
    label: str = "loose"


LOOSE = JudgeConfig()
STANDARD = JudgeConfig(pitch_tolerance_cents=50.0, window_before=0.120,
                       window_after=0.120, judge_string=True, label="standard")
STRICT = JudgeConfig(pitch_tolerance_cents=30.0, window_before=0.080,
                     window_after=0.080, judge_string=True, label="strict")


@dataclass(frozen=True)
class Verdict:
    note: Note
    status: str                  # hit | wrong_pitch | wrong_string | missed | skipped
    detected_midi: int | None = None
    cents: float | None = None
    delta_ms: float | None = None


def judge_phrase(notes: list[Note], detections: list[Detection],
                 cfg: JudgeConfig = LOOSE) -> list[Verdict]:
    """Align expected notes against detections, one pass, in time order."""
    used = [False] * len(detections)
    verdicts: list[Verdict] = []

    for note in notes:
        if cfg.ignore_tech and note.is_tech:
            verdicts.append(Verdict(note, "skipped"))
            continue

        lo = note.start - (cfg.window_before if cfg.judge_onset else 2.0)
        hi = note.start + (cfg.window_after if cfg.judge_onset else 2.0)

        best_idx: int | None = None
        best_delta = 0.0
        for i, det in enumerate(detections):
            if used[i]:
                continue
            if not (lo <= det.time <= hi):
                continue
            delta = abs(det.time - note.start)
            if best_idx is None or delta < best_delta:
                best_idx, best_delta = i, delta

        if best_idx is None:
            verdicts.append(Verdict(note, "missed"))
            continue

        used[best_idx] = True
        det = detections[best_idx]
        cents = (det.midi - note.midi) * 100.0 + det.cents
        delta_ms = (det.time - note.start) * 1000.0

        if abs(cents) <= cfg.pitch_tolerance_cents:
            status = "hit"
        else:
            status = "wrong_pitch"

        # the right pitch on the wrong string is its own verdict: audible to a
        # teacher, invisible to a pitch-only judge
        if (status == "hit" and cfg.judge_string
                and det.string is not None and note.string is not None
                and det.string != note.string):
            status = "wrong_string"

        verdicts.append(Verdict(note, status, det.midi, cents, delta_ms))

    return verdicts


@dataclass
class Summary:
    total: int = 0
    judged: int = 0
    hits: int = 0
    wrong_pitch: int = 0
    wrong_string: int = 0
    missed: int = 0
    skipped: int = 0
    worst_cents: float = 0.0

    @property
    def accuracy(self) -> float:
        """Standard / strict: misses count against you."""
        return self.hits / self.judged if self.judged else 0.0

    @property
    def pitch_accuracy(self) -> float:
        """Loose profile: hit / (hit + wrong_pitch). Misses, string hints and
        skipped notes are listed separately and stay out of the denominator."""
        denom = self.hits + self.wrong_pitch
        return self.hits / denom if denom else 0.0

    def accuracy_for(self, cfg: "JudgeConfig") -> float:
        return self.pitch_accuracy if cfg.label == "loose" else self.accuracy

    @property
    def max_consecutive_misses(self) -> int:   # filled by summarize()
        return getattr(self, "_streak", 0)


def summarize(verdicts: list[Verdict]) -> Summary:
    s = Summary(total=len(verdicts))
    streak = 0
    for v in verdicts:
        if v.status == "skipped":
            s.skipped += 1
            continue
        s.judged += 1
        if v.status == "hit":
            s.hits += 1
            streak = 0
        elif v.status == "wrong_pitch":
            s.wrong_pitch += 1
            streak = 0
        elif v.status == "wrong_string":
            s.wrong_string += 1
            streak = 0
        else:
            s.missed += 1
            streak += 1
            s._streak = max(getattr(s, "_streak", 0), streak)
        if v.cents is not None:
            s.worst_cents = max(s.worst_cents, abs(v.cents))
    return s


def report(verdicts: list[Verdict], cfg: JudgeConfig = LOOSE) -> str:
    s = summarize(verdicts)
    lines = [
        f"profile: {cfg.label}  (+-{cfg.pitch_tolerance_cents:.0f} cents, "
        f"-{cfg.window_before*1000:.0f}/+{cfg.window_after*1000:.0f} ms)",
        f"notes {s.total}  judged {s.judged}  hit {s.hits}  "
        f"wrong {s.wrong_pitch}  string {s.wrong_string}  "
        f"missed {s.missed}  skipped {s.skipped}",
        f"accuracy {s.accuracy_for(cfg)*100:.0f}%   worst deviation {s.worst_cents:+.0f} cents"
        f"   longest miss streak {s.max_consecutive_misses}",
        "",
    ]
    for v in verdicts:
        if v.status == "skipped":
            lines.append(f"  {v.note.start:6.2f}s  {v.note.name:>4}  --  (technique, not judged)")
            continue
        if v.status == "missed":
            lines.append(f"  {v.note.start:6.2f}s  {v.note.name:>4}  XX  missed")
            continue
        mark = "OK" if v.status == "hit" else "!!"
        heard = f"{v.detected_midi}" if v.detected_midi is not None else "-"
        lines.append(
            f"  {v.note.start:6.2f}s  {v.note.name:>4}  {mark}  "
            f"{v.delta_ms:+.0f} ms  {v.cents:+.0f} cents (midi {heard})"
        )
    return "\n".join(lines)
