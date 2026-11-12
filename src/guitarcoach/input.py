"""Device -> judging strategy routing.

Product spec, chapter 7: never run one detector for every input. A bluetooth
headset and an audio interface need different promises, and the UI must say
which promise it is keeping.

The engine returns warning *codes*, not prose: the UI layer localises them.
`warning` is English (CLI); `warning_zh` is the Chinese copy for the web UI.
"""

from __future__ import annotations

from dataclasses import dataclass

WARNINGS: dict[str, str] = {
    "bluetooth_latency": (
        "Bluetooth / high-latency input: pitch only, no timing judgement. "
        "Use a cable when practising."
    ),
    "mic_distance": (
        "Microphone input: stay within 30 cm; room noise lowers accuracy."
    ),
    "builtin_mic": (
        "Built-in microphone: string position is a hint only; "
        "strict judging is not advisable."
    ),
}

WARNINGS_ZH: dict[str, str] = {
    "bluetooth_latency": "当前是蓝牙或高延迟输入，只判音高、不判节奏，练习时请尽量用有线。",
    "mic_distance": "请把麦克风放在离琴约 30 厘米以内，环境噪音会影响准确率。",
    "builtin_mic": "正在用内置麦克风，弦位只作提示，不建议开严格档。",
}

# Device names that almost always mean a Bluetooth audio path.
_BLUETOOTH_MARKS = ("bluetooth", "airpods", "hands-free", "headset",
                    "a2dp", "hfp", "bt ", " bt")


def looks_bluetooth(name: str | None) -> bool:
    n = (name or "").lower()
    return any(m in n for m in _BLUETOOTH_MARKS)


@dataclass(frozen=True)
class InputProfile:
    name: str
    pitch_only: bool          # no timing judgement at all
    judge_onset: bool         # is the arrival time meaningful?
    judge_string: bool        # can we trust string assignment?
    warning_code: str | None = None
    latency_ms: float | None = None

    @property
    def warning(self) -> str | None:
        return WARNINGS.get(self.warning_code) if self.warning_code else None

    @property
    def warning_zh(self) -> str | None:
        return WARNINGS_ZH.get(self.warning_code) if self.warning_code else None

    def describe(self) -> str:
        bits = [f"profile={self.name}",
                f"pitch_only={self.pitch_only}",
                f"timing={self.judge_onset}",
                f"string={self.judge_string}"]
        if self.warning_code:
            bits.append(f"warning={self.warning_code}")
        return "  ".join(bits)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pitch_only": self.pitch_only,
            "judge_onset": self.judge_onset,
            "judge_string": self.judge_string,
            "warning_code": self.warning_code,
            "warning": self.warning_zh,
            "latency_ms": self.latency_ms,
        }


def choose_profile(*, driver: str = "asio", is_bluetooth: bool = False,
                   has_midi: bool = False, sample_rate: int = 44100,
                   latency_ms: float = 15.0,
                   channels: int = 1,
                   device_name: str | None = None) -> InputProfile:
    """Pick a judging strategy for the detected device."""
    if has_midi:
        return InputProfile("midi", pitch_only=False, judge_onset=True,
                            judge_string=True, latency_ms=latency_ms)

    if is_bluetooth or looks_bluetooth(device_name) or latency_ms >= 120.0:
        return InputProfile("degraded-bluetooth", pitch_only=True,
                            judge_onset=False, judge_string=False,
                            warning_code="bluetooth_latency",
                            latency_ms=latency_ms)

    if driver.lower() in ("asio", "coreaudio", "wasapi-exclusive"):
        return InputProfile("interface", pitch_only=False, judge_onset=True,
                            judge_string=True, latency_ms=latency_ms)

    if latency_ms <= 40.0 and sample_rate >= 44100:
        return InputProfile("usb-mic", pitch_only=False, judge_onset=True,
                            judge_string=True, warning_code="mic_distance",
                            latency_ms=latency_ms)

    return InputProfile("builtin-mic", pitch_only=False, judge_onset=True,
                        judge_string=False, warning_code="builtin_mic",
                        latency_ms=latency_ms)
