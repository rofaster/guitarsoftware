"""Score files: a small JSON format that any tab source can be normalised into."""

from __future__ import annotations

import json
from pathlib import Path

from .ir import (DEFAULT_METER, DEFAULT_TEMPO, Note, Score,
                 STANDARD_TUNING, note_from_string_fret)
from .progress import annotate_score


def load_score(path: str | Path) -> Score:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tuning = {int(k): int(v) for k, v in raw.get("tuning", {}).items()} or dict(STANDARD_TUNING)
    notes: list[Note] = []
    for n in raw.get("notes", []):
        string = n.get("string")
        fret = n.get("fret")
        midi = n.get("midi")
        if midi is None:
            if string is None or fret is None:
                raise ValueError(f"note needs midi or (string, fret): {n}")
            midi = note_from_string_fret(string, fret, tuning)
        notes.append(Note(start=float(n["start"]), dur=float(n.get("dur", 0.4)),
                          midi=int(midi), string=string, fret=fret,
                          tech=n.get("tech"), bar=n.get("bar"),
                          phrase_id=n.get("phrase_id")))
    notes.sort(key=lambda x: x.start)
    score = Score(title=raw.get("title", Path(path).stem), tuning=tuning,
                  notes=notes, tempo=float(raw.get("tempo", DEFAULT_TEMPO)),
                  meter=_meter(raw))
    return annotate_score(score)


def _meter(raw: dict) -> tuple[int, int]:
    m = raw.get("meter")
    if isinstance(m, str) and "/" in m:
        a, b = m.split("/", 1)
        return int(a), int(b)
    if isinstance(m, (list, tuple)) and len(m) == 2:
        return int(m[0]), int(m[1])
    if "beats_per_bar" in raw:          # legacy files
        return int(raw["beats_per_bar"]), 4
    return DEFAULT_METER


def save_score(score: Score, path: str | Path) -> None:
    payload = {
        "title": score.title,
        "tempo": score.tempo,
        "meter": f"{score.meter[0]}/{score.meter[1]}",
        "tuning": {str(k): v for k, v in score.tuning.items()},
        "notes": [
            {"start": round(n.start, 3), "dur": round(n.dur, 3),
             "midi": n.midi, "string": n.string, "fret": n.fret,
             **({"tech": n.tech} if n.tech else {}),
             **({"bar": n.bar} if n.bar is not None else {}),
             **({"phrase_id": n.phrase_id} if n.phrase_id is not None else {})}
            for n in score.notes
        ],
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
