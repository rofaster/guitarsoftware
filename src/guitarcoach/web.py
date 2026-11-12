"""Follow-along web UI: one HTML page, a score feed, and an SSE event stream.

Standard library only. The browser gets three things:
  GET /        the page
  GET /score   the notes to draw, plus load-time validation issues
  GET /events  server-sent events:
               hello, detection, verdict, flash, suggest_back, loop, done

  /events query:
    from=<note index>     start here (pause keeps the cursor; play resumes)
    speed=<0.5..1.0>      practice speed
    mode=follow|wait      跟弹 (time runs) or 等待 (advance only on a right pitch)
    skip_from=<index>     notes in [skip_from, from) become `skipped`
    loop_a=<bar> loop_b=<bar>   A-B loop over whole bars

Loose profile rules (docs/v1-music-spec.md): never pause, never jump on its
own, never mark red. Errors only raise a non-blocking "退回上一小节？" prompt.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .audio_input import FileSource
from .hex import HexStreamDetector
from .exercises import builtin_score
from .input import InputProfile, choose_profile, looks_bluetooth
from .ir import Detection, Note, midi_to_name
from .judge import LOOSE, JudgeConfig
from .live import StreamDetector
from .progress import (annotate_score, first_index_of_bar, last_index_of_bar,
                       prev_bar_start)
from .score_io import load_score
from .validate import validate_score

UI_PATH = Path(__file__).parent / "ui" / "index.html"
DEFAULT_SPEED = 0.7
DEFAULT_MODE = "wait"       # 初版默认等待：弹对才前进
MIN_SPEED, MAX_SPEED = 0.5, 1.0
COUNT_IN_BEATS = 1          # 切回跟弹 / resume: one beat before the pending note
STREAK_PROMPT = 5           # 连错 5 个 wrong_pitch
BAR_ERROR_RATE = 0.5        # 单小节错误率 > 50%
BAR_MIN_JUDGED = 2


def _heard(det: Detection | None) -> dict:
    """Optional fields the fretboard uses: omit when unknown."""
    if det is None:
        return {}
    out = {"midi": det.midi}
    if det.string is not None:
        out["string"] = det.string
    if det.fret is not None:
        out["fret"] = det.fret
    return out


def _verdict(index: int, status: str, cents=None, delta_ms=None,
             det: Detection | None = None) -> dict:
    ev = {"type": "verdict", "index": index, "status": status,
          "cents": cents, "delta_ms": delta_ms}
    ev.update(_heard(det))
    return ev


class LiveJudge:
    """跟弹: sequential matcher on a running clock, one expected note at a time.

    Never pauses or jumps by itself. Repeated errors only produce a
    `suggest_back` event, at most once per bar.
    """

    def __init__(self, notes: list[Note], cfg: JudgeConfig = LOOSE):
        self.notes = notes
        self.cfg = cfg
        self.i = 0
        self.end = len(notes)        # A-B loop: notes past B are never judged
        self.hits = 0
        self.judged = 0              # hit + wrong_pitch (loose accuracy denominator)
        self.pitch_streak = 0
        self.bar_stats: dict[int, list[int]] = {}   # bar -> [hit, wrong_pitch, missed]
        self.prompted_bar: int | None = None
        # notes that need judging per bar (technique notes pass for free)
        self.bar_total: dict[int, int] = {}
        for n in notes:
            if not (n.is_tech and cfg.ignore_tech):
                b = n.bar if n.bar is not None else 0
                self.bar_total[b] = self.bar_total.get(b, 0) + 1

    # ---- cursor control ----
    def flush(self) -> list[dict]:
        """End of a finite take: leftover notes are missed, even in pitch-only."""
        out: list[dict] = []
        while self.i < self.end:
            note = self.notes[self.i]
            if note.is_tech and self.cfg.ignore_tech:
                out += self._emit(note, "skipped")
            else:
                out += self._emit(note, "missed")
        return out

    def skip_range(self, start: int, end: int) -> list[dict]:
        """Mark [start, end) as skipped, not missed, and put the cursor at end."""
        out: list[dict] = []
        end = min(end, len(self.notes))
        for k in range(max(0, start), end):
            out.append(_verdict(k, "skipped"))
        self.i = max(self.i, end)
        return out

    def restart_at(self, index: int, bars: set[int] | None = None) -> None:
        """Loop / jump: move the cursor and forget error stats for `bars`."""
        self.i = index
        self.pitch_streak = 0
        self.prompted_bar = None
        for b in (bars or set()):
            self.bar_stats.pop(b, None)

    # ---- judging ----
    def tick(self, now: float) -> list[dict]:
        """Clock advanced to `now` (score time): close windows that ended.

        When `judge_onset` is False (bluetooth / high latency), arrival time
        is ignored: a late right pitch is still a hit, and we never mark a
        note missed just because the clock moved on.
        """
        if not self.cfg.judge_onset:
            return []
        out: list[dict] = []
        while self.i < self.end:
            note = self.notes[self.i]
            if note.is_tech and self.cfg.ignore_tech:
                out += self._emit(note, "skipped")
                continue
            if now > note.start + self.cfg.window_after:
                out += self._emit(note, "missed")
                continue
            break
        return out

    def push(self, det: Detection) -> list[dict]:
        out = self.tick(det.time)
        if self.i >= self.end:
            return out
        note = self.notes[self.i]
        early = 2.0 if not self.cfg.judge_onset else self.cfg.window_before
        if det.time < note.start - early:
            return out                          # too early: ignore it
        cents = (det.midi - note.midi) * 100.0 + det.cents
        if abs(cents) <= self.cfg.pitch_tolerance_cents:
            status = "hit"
            if (det.string is not None and note.string is not None
                    and det.string != note.string):
                status = "wrong_string"
        else:
            status = "wrong_pitch"
        out += self._emit(note, status, cents, (det.time - note.start) * 1000.0, det)
        return out

    def _emit(self, note: Note, status: str, cents=None, delta_ms=None,
              det: Detection | None = None) -> list[dict]:
        index = self.i
        self.i += 1
        if status in ("hit", "wrong_pitch"):
            self.judged += 1
        # loose: a string hint with the right pitch still counts as a hit
        if status == "hit" or (status == "wrong_string" and not self.cfg.judge_string):
            self.hits += 1
        ev = _verdict(index, status, cents, delta_ms, det)
        ev["judged"], ev["hits"] = self.judged, self.hits
        out = [ev]
        prompt = self._check_prompt(note, index, status)
        if prompt:
            out.append(prompt)
        return out

    def _check_prompt(self, note: Note, index: int, status: str) -> dict | None:
        if status not in ("hit", "wrong_pitch", "missed"):
            return None                         # string hints / skipped: neutral
        bar = note.bar if note.bar is not None else 0
        stats = self.bar_stats.setdefault(bar, [0, 0, 0])
        if status == "hit":
            stats[0] += 1
            self.pitch_streak = 0
        elif status == "wrong_pitch":
            stats[1] += 1
            self.pitch_streak += 1
        else:
            stats[2] += 1
            self.pitch_streak = 0
        if self.prompted_bar == bar:
            return None                         # once per bar
        # bar rule: wrong notes already exceed half of the notes this bar has
        # to judge, so the bar's final error rate is certain to be > 50%
        total = self.bar_total.get(bar, 0)
        reason = None
        if self.pitch_streak >= STREAK_PROMPT:
            reason = "streak"
        elif total >= BAR_MIN_JUDGED and stats[1] > total * BAR_ERROR_RATE:
            reason = "bar_rate"
        if reason is None:
            return None
        self.prompted_bar = bar
        self.pitch_streak = 0
        return {"type": "suggest_back", "reason": reason, "bar": bar,
                "target": prev_bar_start(self.notes, index)}


class WaitJudge:
    """等待: the clock stops on the pending note; only a right note advances.

    No time window, so nothing is ever `missed`. A wrong pitch flashes the
    note yellow and stays. If the detection carries a string and it does
    not match the written string, that also flashes yellow and stays —
    this beginner loop is also a string-identification drill. Pitch-only
    input (no string on the detection) still advances on pitch alone.
    No rewind prompts here.
    """

    def __init__(self, notes: list[Note], cfg: JudgeConfig = LOOSE, start: int = 0):
        self.notes = notes
        self.cfg = cfg
        self.i = start
        self.hits = 0
        self.judged = 0

    def _skip_tech(self) -> list[dict]:
        out = []
        while (self.i < len(self.notes) and self.cfg.ignore_tech
               and self.notes[self.i].is_tech):
            out.append(_verdict(self.i, "skipped"))
            self.i += 1
        return out

    def push(self, det: Detection) -> list[dict]:
        out = self._skip_tech()
        if self.i >= len(self.notes):
            return out
        note = self.notes[self.i]
        cents = (det.midi - note.midi) * 100.0 + det.cents
        if abs(cents) > self.cfg.pitch_tolerance_cents:
            ev = {"type": "flash", "index": self.i, "cents": cents,
                  "status": "wrong_pitch"}
            ev.update(_heard(det))
            out.append(ev)
            return out
        if (det.string is not None and note.string is not None
                and det.string != note.string):
            ev = {"type": "flash", "index": self.i, "cents": cents,
                  "status": "wrong_string"}
            ev.update(_heard(det))
            out.append(ev)
            return out
        self.hits += 1
        self.judged += 1
        ev = _verdict(self.i, "hit", cents, None, det)
        ev["judged"], ev["hits"] = self.judged, self.hits
        out.append(ev)
        self.i += 1
        out += self._skip_tech()
        return out


def _judge_from_input(iprof: InputProfile) -> JudgeConfig:
    """Loose musical rules, with timing/string trust taken from the device."""
    return JudgeConfig(
        pitch_tolerance_cents=LOOSE.pitch_tolerance_cents,
        window_before=LOOSE.window_before,
        window_after=LOOSE.window_after,
        judge_string=LOOSE.judge_string and iprof.judge_string,
        judge_onset=iprof.judge_onset,
        ignore_tech=LOOSE.ignore_tech,
        label=LOOSE.label,
    )


def _documents(score, issues=None, iprof: InputProfile | None = None) -> dict:
    return {
        "title": score.title,
        "tempo": score.tempo,
        "meter": list(score.meter),
        "beats_per_bar": score.beats_per_bar,
        "bar_seconds": round(score.bar_seconds, 4),
        "tuning": {str(k): v for k, v in sorted(score.tuning.items())},
        "defaults": {"mode": DEFAULT_MODE, "speed": DEFAULT_SPEED,
                     "profile": LOOSE.label},
        "input": (iprof or choose_profile()).to_dict(),
        "notes": [{"name": midi_to_name(n.midi), "midi": n.midi,
                   "string": n.string, "fret": n.fret,
                   "start": round(n.start, 3), "dur": round(n.dur, 3),
                   "bar": n.bar, "phrase_id": n.phrase_id}
                  for n in score.notes],
        "issues": [i.to_dict() for i in (issues or [])],
    }


def _int_or_none(qs, key):
    raw = qs.get(key, [None])[0]
    return int(raw) if raw not in (None, "") else None


def make_handler(score, source, speed: float,
                 iprof: InputProfile | None = None):
    score = annotate_score(score)
    issues = validate_score(score)
    iprof = iprof or choose_profile()          # file replay: full timing
    cfg = _judge_from_input(iprof)
    docs = _documents(score, issues, iprof)
    notes = score.notes
    state = {"busy": False}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):          # keep the console clean
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:               # noqa: N802
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path in ("/", "/index.html"):
                self._send(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/score":
                body = json.dumps(docs, ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif parsed.path == "/events":
                rate = float(qs.get("speed", [str(speed)])[0])
                if rate > 0:                    # 0 = unthrottled (tests)
                    rate = min(MAX_SPEED, max(MIN_SPEED, rate))
                mode = qs.get("mode", [DEFAULT_MODE])[0]
                if mode not in ("follow", "wait"):
                    mode = DEFAULT_MODE
                self._stream(_int_or_none(qs, "from") or 0, rate, mode,
                             _int_or_none(qs, "skip_from"),
                             _int_or_none(qs, "loop_a"), _int_or_none(qs, "loop_b"))
            else:
                self._send(404, b"not found", "text/plain")

        def _event(self, payload: dict) -> None:
            self.wfile.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode()
                             + b"\n\n")
            self.wfile.flush()

        def _stream(self, start, rate, mode, skip_from, loop_a, loop_b) -> None:
            with lock:
                if state["busy"]:
                    self._send(429, b"busy", "text/plain")
                    return
                state["busy"] = True
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self._run(start, rate, mode, skip_from, loop_a, loop_b)
            except (BrokenPipeError, ConnectionError):  # ConnectionAbortedError on Windows
                pass
            finally:
                state["busy"] = False

        def _run(self, start, rate, mode, skip_from, loop_a, loop_b) -> None:
            n = len(notes)
            start = max(0, min(start, n))

            loop = None
            if loop_a is not None and loop_b is not None:
                a, b = sorted((loop_a, loop_b))
                a_idx, b_idx = first_index_of_bar(notes, a), last_index_of_bar(notes, b)
                if 0 <= a_idx <= b_idx:
                    loop = {"a": a, "b": b, "a_idx": a_idx, "b_idx": b_idx,
                            "a_time": a * score.bar_seconds,
                            "end_time": (b + 1) * score.bar_seconds,
                            "bars": set(range(a, b + 1))}
                    if not a_idx <= start <= b_idx:
                        start = a_idx

            self._event({"type": "hello", "mode": mode, "speed": rate, "from": start,
                         "profile": cfg.label,
                         "defaults": docs["defaults"],
                         "input": iprof.to_dict(),
                         "loop": None if loop is None else [loop["a"], loop["b"]],
                         "score": docs})

            judge = (WaitJudge(notes, cfg, start=start) if mode == "wait"
                     else LiveJudge(notes, cfg))
            if mode == "follow":
                if loop:
                    judge.end = loop["b_idx"] + 1
                if skip_from is not None and skip_from < start:
                    for ev in judge.skip_range(skip_from, start):
                        self._event(ev)
                judge.i = start
            elif skip_from is not None and skip_from < start:
                for k in range(skip_from, start):
                    self._event(_verdict(k, "skipped"))

            beat = score.beat_seconds
            origin = notes[start].start if start < n else 0.0
            anchor = origin - COUNT_IN_BEATS * beat      # score time at audio t=0
            is_file = isinstance(source, FileSource)
            if mode == "follow":
                self._event({"type": "count_in", "beats": COUNT_IN_BEATS,
                             "seconds": COUNT_IN_BEATS * beat / (rate or 1.0)})

            def open_audio(at: float):
                if is_file:
                    st = max(0.0, at)
                    return st, source.blocks(start_time=st)
                return at, source.blocks()

            # file replay: detections are already in score time (the take was
            # recorded at 1.0x), so time_scale = 1. A live device runs at `rate`.
            time_scale = 1.0 if is_file else (rate or 1.0)
            anchor, blocks = open_audio(anchor)
            detector = (HexStreamDetector(source.sr)
                        if getattr(source, "hex", False) else StreamDetector(source.sr))
            clock = time.monotonic()
            played = 0.0                                  # audio seconds fed so far

            def score_time(t_audio: float) -> float:
                return anchor + t_audio * time_scale

            while True:
                restarted = False
                for block in blocks:
                    if judge.i >= n and loop is None:
                        break
                    dets = detector.push(block)
                    played = detector.total / source.sr
                    for det in dets:
                        latency_ms = (played - det.time) * 1000.0
                        t = score_time(det.time)
                        ev = {"type": "detection", "time": t,
                              "name": midi_to_name(det.midi), "midi": det.midi,
                              "cents": det.cents, "latency_ms": latency_ms}
                        ev.update(_heard(det))
                        self._event(ev)
                        shifted = Detection(time=t, midi=det.midi, cents=det.cents,
                                            confidence=det.confidence,
                                            string=det.string, fret=det.fret)
                        for ev in judge.push(shifted):
                            self._event(ev)
                    if mode == "follow":
                        now = score_time(played)
                        for ev in judge.tick(now):
                            self._event(ev)
                        if loop and now >= loop["end_time"] + judge.cfg.window_after:
                            # wrap without a silent gap: keep the overshoot
                            over = now - loop["end_time"]
                            judge.restart_at(loop["a_idx"], loop["bars"])
                            self._event({"type": "loop", "index": loop["a_idx"]})
                            if is_file:
                                anchor, blocks = open_audio(loop["a_time"] - beat)
                                detector = (HexStreamDetector(source.sr)
                                            if getattr(source, "hex", False)
                                            else StreamDetector(source.sr))
                                clock, played = time.monotonic(), 0.0
                                restarted = True
                                break
                            anchor += (loop["a_time"] + over) - now
                    elif loop and judge.i > loop["b_idx"]:
                        judge.i = loop["a_idx"]
                        self._event({"type": "loop", "index": loop["a_idx"]})
                    if rate > 0:
                        lead = played / rate - (time.monotonic() - clock)
                        if lead > 0:
                            time.sleep(lead)
                if not restarted:
                    break

            if mode == "follow":
                # end of the take: close windows that really ended. In pitch-only
                # (bluetooth) mode tick never misses, so flush the leftovers.
                for ev in judge.tick(score_time(played)):
                    self._event(ev)
                if not judge.cfg.judge_onset:
                    for ev in judge.flush():
                        self._event(ev)
            self._event({"type": "done"})

    return Handler


def serve(score, source, host: str = "127.0.0.1", port: int = 8765,
          speed: float = DEFAULT_SPEED, iprof: InputProfile | None = None) -> None:
    handler = make_handler(score, source, speed, iprof)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    print(f"listening on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> None:
    from .audio_input import DeviceSource, FileSource as WavSource

    ap = argparse.ArgumentParser(prog="guitarcoach.web")
    ap.add_argument("--score", type=Path, help="JSON score; default: built-in open-string exercise")
    ap.add_argument("--wav", type=Path, help="replay this file instead of a device")
    ap.add_argument("--device", type=int, help="sounddevice input index")
    ap.add_argument("--hex", action="store_true",
                    help="open the device as a 6-channel hexaphonic pickup "
                         "(string 1 = channel 0). 6-channel WAVs are detected automatically")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                    help="practice speed 0.5-1.0; default 0.7")
    ap.add_argument("--bluetooth", action="store_true",
                    help="treat the input as Bluetooth: pitch only, no timing")
    ap.add_argument("--latency-ms", type=float, default=None,
                    help="measured input latency; 120 ms or more also degrades "
                         "to pitch-only judging")
    args = ap.parse_args(argv)

    score = load_score(args.score) if args.score else builtin_score()
    for issue in validate_score(annotate_score(score)):
        print(f"[谱面检查] {issue.message}"
              + (f"  note #{issue.index}" if issue.index is not None else ""))
    if args.wav:
        source = WavSource(args.wav)
        if args.hex and not source.hex:
            ap.error("--hex needs a 6-channel WAV (channel 0 = string 1). "
                     "Render one with: python -m guitarcoach.hex --out take.wav")
        device_name = None
    elif args.device is not None:
        source = DeviceSource(args.device, hexaphonic=args.hex)
        device_name = None
        try:
            import sounddevice as sd
            device_name = sd.query_devices(args.device)["name"]
        except Exception:
            pass
        if looks_bluetooth(device_name):
            args.bluetooth = True
    else:
        ap.error("need --wav or --device")

    latency = args.latency_ms if args.latency_ms is not None else (180.0 if args.bluetooth else 15.0)
    iprof = choose_profile(is_bluetooth=args.bluetooth, latency_ms=latency,
                           device_name=device_name,
                           driver="wasapi" if args.device is not None else "asio")
    if iprof.warning_zh:
        print(f"[输入] {iprof.warning_zh}")
    serve(score, source, args.host, args.port, args.speed, iprof)


if __name__ == "__main__":
    main()
