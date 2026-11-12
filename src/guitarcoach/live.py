"""Streaming note detection: the same maths as `detect_notes`, fed block by block.

Batch detection waits for the whole take; a practice tool cannot. This detector
keeps a rolling buffer, computes one spectral-flux frame per hop as samples
arrive, fires an onset as soon as its peak is confirmed, and resolves the pitch
once enough samples after the attack exist.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .detect import _stable_pitch
from .ir import Detection


@dataclass
class _Pending:
    onset_sample: int
    flux: float


class StreamDetector:
    """Feed it blocks of mono float samples; it yields Detections in order."""

    def __init__(self, sr: int, hop: int = 256, win: int = 1024,
                 frame_size: int = 1536, attack_offset: float = 0.020,
                 min_gap: float = 0.07, delta: float = 0.10,
                 keep_s: float = 3.0, min_confidence: float = 0.10):
        self.sr = sr
        self.hop = hop
        self.win = win
        self.frame_size = frame_size
        self.attack = int(attack_offset * sr)
        self.min_gap_samples = int(min_gap * sr)
        self.delta = delta
        self.keep = int(keep_s * sr)
        self.min_confidence = min_confidence

        self._buf = np.zeros(0, dtype=np.float64)
        self._offset = 0                 # absolute index of _buf[0]
        self.total = 0                   # absolute samples received
        self._frame = 0                  # next frame index to analyse
        self._prev_mag: np.ndarray | None = np.zeros(win // 2 + 1)
        self._flux: deque[float] = deque(maxlen=48)
        self._flux_peak = 1e-9
        self._last_onset = -10 ** 9
        self._pending: list[_Pending] = []
        self._taper = np.hanning(win)

    # ------------------------------------------------------------------ public
    def push(self, block: np.ndarray) -> list[Detection]:
        b = np.asarray(block, dtype=np.float64)
        if b.size == 0:
            return []
        self._buf = np.concatenate([self._buf, b])
        self.total += b.size
        self._trim()

        self._analyse_frames()
        return self._resolve()

    @property
    def buffered_seconds(self) -> float:
        return self._buf.size / self.sr

    # ----------------------------------------------------------------- private
    def _trim(self) -> None:
        drop = self._buf.size - self.keep
        if drop > 0:
            self._buf = self._buf[drop:]
            self._offset += drop

    def _analyse_frames(self) -> None:
        while self._frame + self.win <= self.total:
            start = self._frame - self._offset
            seg = self._buf[start:start + self.win] * self._taper
            mag = np.abs(np.fft.rfft(seg))
            if self._prev_mag is not None:
                diff = mag - self._prev_mag
                flux = float(np.sum(diff[diff > 0]))
            else:
                flux = float(np.sum(mag))
            # Always record flux, including exact zeros from digital silence.
            # Hex channels are quiet until that string is played; if zeros were
            # skipped, the median at the attack would be made of the attack
            # itself and a two-frame rise could never clear the threshold.
            self._flux.append(flux)
            if flux > 0.0:
                self._flux_peak = max(self._flux_peak, flux)
            if len(self._flux) >= 3:
                self._maybe_onset(self._frame - self.hop)
            elif (len(self._flux) == 1 and self._frame == 0 and flux > 0.0):
                # the take starts mid-stream: frame zero is an onset out of
                # silence, and it can never be the middle of three peaks
                self._last_onset = 0
                self._pending.append(_Pending(0, 1.0))
            self._prev_mag = mag
            self._frame += self.hop

    def _maybe_onset(self, frame_sample: int) -> None:
        """`frame_sample` is the absolute sample where the peak frame starts."""
        f = list(self._flux)
        left, mid, right = f[-3], f[-2], f[-1]
        thr = float(np.median(f[:-1])) + self.delta * self._flux_peak
        if not (mid > thr and mid >= left and mid >= right):
            return
        onset = frame_sample
        if onset - self._last_onset < self.min_gap_samples:
            return
        self._last_onset = onset
        self._pending.append(_Pending(onset, mid / self._flux_peak))

    def _resolve(self) -> list[Detection]:
        out: list[Detection] = []
        still: list[_Pending] = []
        for p in self._pending:
            # the voters slide up to 45 ms past the frame start, so wait for
            # that much audio before resolving
            need = (p.onset_sample + self.attack + int(0.045 * self.sr)
                    + self.frame_size)
            if self.total < need:
                still.append(p)
                continue
            start = p.onset_sample + self.attack - self._offset
            # hand over extra samples: _stable_pitch slides its own voters
            # forward from `start`, so the slice must be longer than one frame
            tail = self.frame_size + int(0.05 * self.sr)
            frame = self._buf[start:start + tail]
            m = _stable_pitch(frame, self.sr, 0, self.frame_size) if frame.size >= self.frame_size else 0.0
            if m == 0.0 or p.flux < self.min_confidence:
                continue
            nearest = int(round(m))
            out.append(Detection(time=p.onset_sample / self.sr, midi=nearest,
                                 cents=(m - nearest) * 100.0,
                                 confidence=min(1.0, p.flux)))
        self._pending = still
        out.sort(key=lambda d: d.time)
        return out


def main(argv: list[str] | None = None) -> None:
    """Replay a file as a live stream (or read a device) and print verdicts."""
    import argparse
    import time
    from pathlib import Path

    from .audio_input import DeviceSource, FileSource
    from .ir import midi_to_name
    from .judge import LOOSE, judge_phrase, report
    from .score_io import load_score

    ap = argparse.ArgumentParser(prog="guitarcoach.live")
    ap.add_argument("--wav", type=Path, help="replay this file as a live stream")
    ap.add_argument("--score", type=Path, help="score to judge against")
    ap.add_argument("--device", type=int, help="sounddevice input index")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="1.0 = real time, 0 = as fast as possible")
    args = ap.parse_args(argv)

    if args.wav:
        source = FileSource(args.wav)
    elif args.device is not None:
        source = DeviceSource(args.device)
    else:
        ap.error("need --wav or --device")

    det = StreamDetector(source.sr)
    print(f"listening at {source.sr} Hz, block {source.block} samples "
          f"({source.block / source.sr * 1000:.0f} ms)")
    if args.score:
        score = load_score(args.score)
        print(f"score: {score.title} ({len(score.notes)} notes)\n")
    else:
        score = None

    heard = []
    fed = 0
    clock = time.monotonic()
    try:
        for block in source.blocks():
            for d in det.push(block):
                fed = det.total
                latency_ms = (fed / source.sr - d.time) * 1000
                print(f"[{d.time:6.2f}s] heard {midi_to_name(d.midi):>4} "
                      f"{d.cents:+5.1f}c   latency {latency_ms:5.0f} ms")
                heard.append(d)
            if args.speed > 0:
                target = fed / source.sr / args.speed
                lead = target - (time.monotonic() - clock)
                if lead > 0:
                    time.sleep(lead)
    except KeyboardInterrupt:
        print("\nstopped")

    if score is not None and heard:
        print()
        print(report(judge_phrase(score.notes, heard, LOOSE), LOOSE))


if __name__ == "__main__":
    main()