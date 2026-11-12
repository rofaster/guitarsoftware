"""WAV input/output with the standard library only.

Real takes arrive as files for now; live streaming lands in the next slice.
Mono is the default. A 6-channel file is a hexaphonic take (one string per
channel) and is kept as (n, 6) when mixdown=False.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def load_wav(path: str | Path, *, mixdown: bool = True) -> tuple[np.ndarray, int]:
    """Return (samples in -1..1, sample rate).

    By default a multi-channel file is mixed to mono (shape (n,)), which is
    what the rest of the engine expects. Pass mixdown=False to keep the
    channels: mono stays (n,), otherwise (n, channels).
    """
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())

    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = (b[:, 0].astype(np.int32)
                | (b[:, 1].astype(np.int32) << 8)
                | (b[:, 2].astype(np.int32) << 16))
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        data = ints.astype(np.float64) / float(1 << 23)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / float(1 << 31)
    else:
        raise ValueError(f"unsupported sample width: {width}")

    if channels > 1:
        data = data.reshape(-1, channels)
        if mixdown:
            data = data.mean(axis=1)
    return data, sr


def save_wav(path: str | Path, samples: np.ndarray, sr: int) -> None:
    """16-bit WAV. Mono (n,) or multi-channel (n, ch). No normalisation."""
    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    elif pcm.ndim != 2:
        raise ValueError(f"samples must be (n,) or (n, ch), got {pcm.shape}")
    n, ch = pcm.shape
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())
