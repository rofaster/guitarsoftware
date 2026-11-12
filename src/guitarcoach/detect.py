"""Pitch and onset detection.

YIN (de Cheveigne & Kawahara, 2002) for monophonic pitch, plus spectral-flux
onset detection so overlapping decays still register as separate notes.
Deliberately dependency-light: numpy only.
"""

from __future__ import annotations

import numpy as np

from .ir import Detection, freq_to_midi


def yin_pitch(frame: np.ndarray, sr: int,
              fmin: float = 70.0, fmax: float = 1300.0,
              threshold: float = 0.15) -> float:
    """Return the fundamental frequency of `frame`, or 0.0 if unvoiced."""
    x = np.asarray(frame, dtype=np.float64)
    x = x - x.mean()
    n = len(x)
    tau_min = max(2, int(sr / fmax))
    tau_max = min(int(sr / fmin), n // 2)
    if tau_max <= tau_min + 1:
        return 0.0

    d = np.zeros(tau_max + 1)
    for tau in range(1, tau_max + 1):
        diff = x[: n - tau] - x[tau:]
        d[tau] = float(np.dot(diff, diff))

    cmnd = np.ones(tau_max + 1)
    running = 0.0
    for tau in range(1, tau_max + 1):
        running += d[tau]
        cmnd[tau] = d[tau] * tau / running if running > 1e-12 else 1.0

    tau = 0
    for t in range(tau_min, tau_max):
        if cmnd[t] < threshold:
            while t + 1 <= tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            tau = t
            break
    if tau == 0:
        tau = int(np.argmin(cmnd[tau_min:tau_max]) + tau_min)

    shift = 0.0
    if 0 < tau < tau_max:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = a - 2 * b + c
        if abs(denom) > 1e-12:
            shift = 0.5 * (a - c) / denom

    if cmnd[tau] > 0.6:      # no clear periodicity -> unvoiced
        return 0.0
    return sr / (tau + shift)


def spectral_flux(x: np.ndarray, sr: int,
                  hop: int = 256, win: int = 1024) -> np.ndarray:
    """Positive spectral difference per frame: robust to overlapping decays."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) < win:
        return np.zeros(0)
    frames = 1 + (len(x) - win) // hop
    window = np.hanning(win)
    prev = np.zeros(win // 2 + 1)
    flux = np.zeros(frames)
    for k in range(frames):
        seg = x[k * hop: k * hop + win] * window
        mag = np.abs(np.fft.rfft(seg))
        diff = mag - prev          # frame 0 compares against silence
        flux[k] = float(np.sum(diff[diff > 0]))
        prev = mag
    return flux


def pick_onsets(flux: np.ndarray, sr: int, hop: int,
                delta: float = 0.10, min_gap: float = 0.07) -> list[int]:
    """Adaptive-threshold peak picking on the flux curve."""
    if flux.size == 0 or flux.max() <= 1e-9:
        return []
    f = flux / flux.max()
    k = 9
    padded = np.pad(f, k, mode="edge")
    local_mean = np.convolve(padded, np.ones(2 * k + 1) / (2 * k + 1),
                             mode="same")[k:-k]
    thr = local_mean + delta

    peaks: list[int] = []
    last = -10 ** 9
    gap = min_gap * sr / hop
    # a take may begin on the very first frame, where there is no rising edge
    if f.size and f[0] >= max(thr[0], 0.25):
        peaks.append(0)
        last = 0
    for i in range(1, len(f) - 1):
        if f[i] > thr[i] and f[i] >= f[i - 1] and f[i] >= f[i + 1]:
            if i - last >= gap:
                peaks.append(i)
                last = i
    return peaks


def _peak_near(spec: np.ndarray, bin_hz: float, f: float) -> float:
    idx = int(round(f / bin_hz))
    if idx <= 0 or idx >= len(spec):
        return 0.0
    lo, hi = max(0, idx - 1), min(len(spec), idx + 2)
    return float(spec[lo:hi].max())


def harmonic_ratio(spec: np.ndarray, bin_hz: float, f0: float,
                   n_harm: int = 8) -> float:
    """Energy sitting on the harmonics vs. between them.

    A true fundamental puts energy at k*f0 and leaves (k+0.5)*f0 empty, so the
    ratio is high. A subharmonic (f0/2) only fills the even slots and leaves
    (k+0.5)*f0 sitting on real partials, so its ratio drops. This is what
    distinguishes a genuine low note from an octave-down estimate — unlike
    "the strongest spectral peak", which a plucked string defeats routinely.
    """
    on = 0.0
    off = 0.0
    for k in range(1, n_harm + 1):
        on += _peak_near(spec, bin_hz, f0 * k)
        off += _peak_near(spec, bin_hz, f0 * (k + 0.5))
    return (on + 1e-9) / (off + 1e-9)


def _estimate_f0(frame: np.ndarray, sr: int) -> float:
    """YIN, then a one-way, evidence-gated octave repair.

    YIN's failure mode is locking one period too long, so the estimate can be
    an octave low. The repair only ever doubles, and only when the fundamental
    at f0 is essentially absent *and* the doubled series explains the spectrum
    much better.

    A plain ratio comparison is not enough: a previous string's ringing lands
    on the half-harmonic positions and inflates the denominator — that is how a
    real A2 (YIN: 109 Hz) got promoted to A3 on a recorded take.
    """
    f0 = yin_pitch(frame, sr, threshold=0.12)
    if f0 <= 0:
        return 0.0

    spec = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
    bin_hz = sr / len(frame)

    mag_f0 = _peak_near(spec, bin_hz, f0)
    mag_2f0 = _peak_near(spec, bin_hz, 2.0 * f0)
    if mag_f0 >= 0.25 * mag_2f0:
        return f0                      # fundamental present: trust YIN

    doubled = 2.0 * f0
    if not (70.0 <= doubled <= 1300.0):
        return f0
    if harmonic_ratio(spec, bin_hz, doubled) > 1.3 * harmonic_ratio(spec, bin_hz, f0):
        return doubled
    return f0


def _stable_pitch(x: np.ndarray, sr: int, start: int,
                  frame_size: int,
                  offsets: tuple[float, ...] = (0.008, 0.024, 0.045)) -> float:
    """Median pitch over a few frames after the attack.

    Voting over several frames removes single-frame estimates that land an
    octave away; the harmonic ratio inside `_estimate_f0` catches the ones
    that survive the vote.
    """
    readings: list[float] = []
    for offset_s in offsets:
        s = start + int(offset_s * sr)
        frame = x[s:s + frame_size]
        if len(frame) < frame_size:
            break
        f0 = _estimate_f0(frame, sr)
        if f0 > 0:
            readings.append(freq_to_midi(f0))
    if not readings:
        return 0.0
    return float(np.median(readings))


# Notes closer than this cannot be separated by a monophonic estimator: the
# previous string's decay is still comparable to the new attack. Measured with
# tools/probe_overlap.py. Adaptive windows (short window near the attack,
# pitch-dependent fallback) were tried and reverted: they fixed 0.10-0.15 s
# but broke 0.20-0.25 s, and a short window reports low notes an octave high.
TIGHT_GAP_S = 0.25


def detect_notes(x: np.ndarray, sr: int,
                 hop: int = 256,
                 frame_size: int = 1536,
                 min_confidence: float = 0.10,
                 attack_offset: float = 0.020,
                 offsets: tuple[float, ...] = (0.008, 0.024, 0.045)) -> list[Detection]:
    """Segment the signal into notes and estimate each one's pitch.

    One fixed window for every note. The window is long enough for the low
    strings (E2 needs ~35 ms) and short enough to stay inside a note at
    practice tempo. Separating notes closer than TIGHT_GAP_S needs spectral
    subtraction or a polyphonic estimator, not a cleverer window.
    """
    x = np.asarray(x, dtype=np.float64)
    if len(x) < frame_size:
        return []

    flux = spectral_flux(x, sr, hop=hop)
    if flux.size == 0:
        return []
    onsets = pick_onsets(flux, sr, hop)
    peak_flux = float(flux.max()) or 1.0

    out: list[Detection] = []
    for i in onsets:
        start = i * hop + int(attack_offset * sr)
        m = _stable_pitch(x, sr, start, frame_size, offsets)
        if m == 0.0:
            continue
        nearest = int(round(m))
        cents = (m - nearest) * 100.0
        conf = float(min(1.0, flux[i] / peak_flux))
        if conf < min_confidence:
            continue
        out.append(Detection(time=i * hop / sr, midi=nearest,
                             cents=cents, confidence=conf))
    return out