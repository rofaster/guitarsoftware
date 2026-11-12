"""Decode any audio file (m4a/aac/wav/...) to 44.1 kHz mono WAV.

    uv run --with numpy --with av python tools/import_audio.py IN OUT.wav
"""

import sys
from pathlib import Path

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import save_wav  # noqa: E402

TARGET_SR = 44100


def decode(path: Path) -> tuple[np.ndarray, int, int]:
    container = av.open(str(path))
    stream = container.streams.audio[0]
    src_sr = stream.rate or 44100
    channels = stream.codec_context.channels or 1

    resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_SR)
    chunks = []
    for frame in container.decode(stream):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    container.close()

    data = np.concatenate(chunks) if chunks else np.zeros(0)
    return data.astype(np.float64), TARGET_SR, src_sr, channels


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data, sr, src_sr, channels = decode(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    save_wav(dst, data, sr)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    print(f"src {src.name}")
    print(f"  source: {src_sr} Hz, {channels} ch")
    print(f"  out   : {sr} Hz mono, {len(data)/sr:.2f} s, peak {peak:.3f}")
    print(f"  file  : {dst}")


if __name__ == "__main__":
    main()