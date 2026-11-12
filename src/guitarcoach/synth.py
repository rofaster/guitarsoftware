"""Karplus-Strong plucked-string synthesis.

Used only for tests and the demo: it lets the whole judge pipeline run with
no guitar and no audio hardware.

`brightness` stands in for string gauge: a thick low string damps the high
partials, a thin high string keeps them. That difference is what makes string
identification possible at all, so the synth has to model it.
"""

from __future__ import annotations

import numpy as np

SR = 44100

# thicker string -> darker excitation. 1.0 is a plain noise burst (the original
# behaviour), lower values low-pass the excitation.
STRING_BRIGHTNESS: dict[int, float] = {6: 0.30, 5: 0.42, 4: 0.55,
                                       3: 0.68, 2: 0.84, 1: 0.96}


def pluck(freq: float, dur: float, sr: int = SR,
          decay: float = 0.996, brightness: float = 1.0,
          seed: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    delay = max(2, int(round(sr / freq)))
    # a Karplus-Strong loop can only hold an integer delay, so the naive pitch
    # is sr/delay; resample to land on the requested frequency instead.
    pitch_scale = (sr / delay) / freq

    noise = rng.uniform(-1.0, 1.0, delay)
    a = max(0.01, min(1.0, brightness))     # a = 1 leaves the burst untouched
    buf = np.empty(delay)
    acc = 0.0
    for i, v in enumerate(noise):
        acc = (1.0 - a) * acc + a * v
        buf[i] = acc
    peak = float(np.max(np.abs(buf))) or 1.0
    buf /= peak

    n = int(dur * sr)
    out = np.empty(n)
    idx = 0
    # string gauge lives in the loop filter, not only in the excitation: a thick
    # string damps its high partials faster, and that difference lasts for the
    # whole note (brightness 1.0 keeps the original 50/50 averaging).
    blend = min(0.9, max(0.5, 0.5 + (1.0 - max(0.0, min(1.0, brightness))) * 0.5))
    for i in range(n):
        out[i] = buf[idx]
        nxt = buf[(idx + 1) % delay]
        buf[idx] = decay * (blend * buf[idx] + (1.0 - blend) * nxt)
        idx = (idx + 1) % delay
    if abs(pitch_scale - 1.0) > 1e-4:
        m = max(8, int(len(out) / pitch_scale))
        out = np.interp(np.arange(m) * pitch_scale, np.arange(len(out)), out)
    fade = min(len(out), int(0.02 * sr))
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out * 0.8


def render(events, total: float, sr: int = SR) -> np.ndarray:
    """events: iterable of (start_s, freq_hz, dur_s, seed[, brightness])."""
    n = int(total * sr)
    mix = np.zeros(n)
    for ev in events:
        start, freq, dur, seed = ev[0], ev[1], ev[2], ev[3]
        brightness = ev[4] if len(ev) > 4 else 1.0
        sig = pluck(freq, dur, sr, brightness=brightness, seed=seed)
        i = int(start * sr)
        j = min(n, i + len(sig))
        if i < n:
            mix[i:j] += sig[: j - i]
    peak = float(np.max(np.abs(mix))) or 1.0
    return mix / peak * 0.9