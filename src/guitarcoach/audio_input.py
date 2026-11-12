"""Audio sources: a real device (optional) or a file replayed as a stream.

`sounddevice` is an optional dependency: the engine and its tests must work
without any audio hardware, so every path has a file-backed equivalent.

A 6-channel source is treated as a hexaphonic pickup: channel 0 is string 1
(high E), channel 5 is string 6 (low E). Stereo is mixed down to mono.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np

from .audio_io import load_wav

HEX_CHANNELS = 6


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    channels: int
    default_samplerate: float
    hostapi: str


def list_devices() -> list[DeviceInfo]:
    """Enumerate input devices. Returns an empty list when sounddevice is absent."""
    try:
        import sounddevice as sd          # noqa: F401  (optional)
    except Exception:
        return []
    out: list[DeviceInfo] = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) <= 0:
            continue
        host = sd.query_hostapis(d["hostapi"])["name"] if "hostapi" in d else ""
        out.append(DeviceInfo(index=i, name=d["name"],
                              channels=int(d["max_input_channels"]),
                              default_samplerate=float(d["default_samplerate"]),
                              hostapi=host))
    return out


class ArraySource:
    """In-memory take, the test double for a mic or a hex pickup.

    `data` is (n,) mono or (n, 6) hexaphonic.
    """

    def __init__(self, data: np.ndarray, sr: int, block_ms: float = 20.0):
        self.data = np.asarray(data, dtype=np.float64)
        self.sr = int(sr)
        self.block = max(1, int(self.sr * block_ms / 1000.0))
        if self.data.ndim == 2 and self.data.shape[1] >= HEX_CHANNELS:
            self.data = self.data[:, :HEX_CHANNELS]
            self.n_channels = HEX_CHANNELS
        elif self.data.ndim == 2:
            self.data = self.data.mean(axis=1)
            self.n_channels = 1
        else:
            self.n_channels = 1

    @property
    def hex(self) -> bool:
        return self.n_channels == HEX_CHANNELS

    def blocks(self, start_time: float = 0.0) -> Iterator[np.ndarray]:
        begin = max(0, int(round(start_time * self.sr)))
        for start in range(begin, len(self.data), self.block):
            yield self.data[start:start + self.block]


class FileSource(ArraySource):
    """Replays a WAV file as fixed-size blocks: the test double for a mic.

    A 6-channel WAV is kept as hexaphonic; anything else is mixed to mono.
    """

    def __init__(self, path, block_ms: float = 20.0):
        data, sr = load_wav(path, mixdown=False)
        super().__init__(data, sr, block_ms=block_ms)
        self.path = path


class DeviceSource:
    """A live input stream from sounddevice (requires the optional package).

    Pass hexaphonic=True (or use a device with at least 6 input channels and
    hexaphonic=True) to open 6 channels and treat them as strings 1-6.
    """

    def __init__(self, device: int | None = None, sr: int = 44100,
                 block_ms: float = 20.0, hexaphonic: bool = False):
        import sounddevice as sd
        self._sd = sd
        self.sr = int(sd.query_device(device)["default_samplerate"]) if device is not None else sr
        self.block = max(1, int(self.sr * block_ms / 1000.0))
        self._device = device
        self.n_channels = HEX_CHANNELS if hexaphonic else 1
        self._queue: list[np.ndarray] = []

    @property
    def hex(self) -> bool:
        return self.n_channels == HEX_CHANNELS

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if self.n_channels == 1:
            self._queue.append(indata[:, 0].copy())
        else:
            self._queue.append(indata[:, :self.n_channels].copy())

    def blocks(self) -> Iterator[np.ndarray]:
        with self._sd.InputStream(device=self._device, channels=self.n_channels,
                                  samplerate=self.sr, blocksize=self.block,
                                  callback=self._callback):
            while True:
                if self._queue:
                    yield self._queue.pop(0)
                else:
                    self._sd.sleep(5)
