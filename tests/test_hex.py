import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import load_wav, save_wav                      # noqa: E402
from guitarcoach.exercises import builtin_score                          # noqa: E402
from guitarcoach.hex import (HexPluck, HexStreamDetector, hex_source,    # noqa: E402
                             plucks_from_score, render_hex,
                             string_overrides)
from guitarcoach.ir import Detection, Note, fret_from_string_midi        # noqa: E402
from guitarcoach.synth import SR                                         # noqa: E402
from guitarcoach.web import LiveJudge, make_handler                      # noqa: E402


class TestFingering(unittest.TestCase):
    def test_legal_and_illegal(self):
        self.assertEqual(fret_from_string_midi(3, 55), 0)     # G open
        self.assertEqual(fret_from_string_midi(4, 55), 5)     # same pitch, D string
        self.assertIsNone(fret_from_string_midi(1, 40))       # high E can't play E2


class TestHexRender(unittest.TestCase):
    def test_energy_lands_on_the_written_channel(self):
        audio = render_hex([HexPluck(0.05, 55, 3, dur=0.4, seed=0)], 0.8)
        self.assertEqual(audio.shape, (int(0.8 * SR), 6))
        rms = np.sqrt((audio ** 2).mean(axis=0))
        self.assertEqual(int(np.argmax(rms)), 2)              # channel 2 = string 3
        self.assertLess(rms.sum() - rms[2], rms[2] * 0.05)

    def test_wav_roundtrip_keeps_six_channels(self):
        audio = render_hex([HexPluck(0.05, 64, 1, dur=0.3, seed=2)], 0.6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hex.wav"
            save_wav(path, audio, SR)
            back, sr = load_wav(path, mixdown=False)
            self.assertEqual(sr, SR)
            self.assertEqual(back.shape[1], 6)
            # default load still mixes to mono, so existing tests stay valid
            mono, _ = load_wav(path)
            self.assertEqual(mono.ndim, 1)


class TestHexDetector(unittest.TestCase):
    def _hear(self, plucks, total):
        src = hex_source(plucks, total)
        det = HexStreamDetector(src.sr)
        heard = []
        for block in src.blocks():
            heard.extend(det.push(block))
        return heard

    def test_string_and_fret_from_channel(self):
        heard = self._hear([HexPluck(0.15, 55, 3, dur=0.5, seed=1)], 1.2)
        on_g = [d for d in heard if d.string == 3]
        self.assertTrue(on_g, f"heard {heard}")
        # Karplus-Strong can land a semitone off; fret still follows midi + string
        d = on_g[0]
        self.assertEqual(d.fret, fret_from_string_midi(3, d.midi))

    def test_same_pitch_on_another_string(self):
        # G3 written on string 3, played on string 4 (fret 5)
        heard = self._hear([HexPluck(0.15, 55, 4, dur=0.5, seed=3)], 1.2)
        on_d = [d for d in heard if d.string == 4]
        self.assertTrue(on_d, f"heard {heard}")
        self.assertTrue(all(d.string == 4 for d in on_d))

    def test_open_strings_land_on_written_channels(self):
        score = builtin_score()
        plucks = plucks_from_score(score)[:4]          # 6, 5, 4, 3
        heard = self._hear(plucks, plucks[-1].start + 1.0)
        strings = {d.string for d in heard}
        self.assertTrue(strings)
        self.assertTrue(strings <= {6, 5, 4, 3}, f"leaked onto {strings}: {heard}")

    def test_open_g_at_2_25_is_detected(self):
        # hop alignment at 2.25s used to miss this isolated G-string attack
        heard = self._hear([HexPluck(2.25, 55, 3, dur=0.75, seed=3)], 3.5)
        on_g = [d for d in heard if d.string == 3 and abs(d.time - 2.25) < 0.2]
        self.assertTrue(on_g, f"missed G3 at 2.25s: {heard}")
        self.assertEqual(on_g[0].midi, 55)

    def test_every_open_string_note_is_detected(self):
        score = builtin_score()
        plucks = plucks_from_score(score)
        heard = self._hear(plucks, plucks[-1].start + plucks[-1].dur + 0.5)
        missing = []
        for i, n in enumerate(score.notes):
            near = [d for d in heard
                    if d.string == n.string and abs(d.time - n.start) < 0.25
                    and abs(d.midi - n.midi) <= 1]
            if not near:
                missing.append(i)
        self.assertFalse(missing, f"missed notes {missing}; heard {[(round(d.time,3), d.midi, d.string) for d in heard]}")


class TestHexEvents(unittest.TestCase):
    def test_verdict_carries_played_string(self):
        note = Note(start=0.0, dur=0.4, midi=55, string=3, fret=0)
        out = LiveJudge([note]).push(Detection(0.02, 55, string=4, fret=5))
        ev = out[0]
        self.assertEqual(ev["status"], "wrong_string")
        self.assertEqual(ev["string"], 4)
        self.assertEqual(ev["fret"], 5)
        self.assertEqual(ev["midi"], 55)

    def test_stream_hello_and_detection_fields(self):
        score = builtin_score()
        src = hex_source(plucks_from_score(score)[:4], 4.0)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                    make_handler(score, src, speed=0.0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/events?speed=0&mode=follow"
            events = []
            with urllib.request.urlopen(url, timeout=30) as r:
                for raw in r:
                    line = raw.decode().strip()
                    if not line.startswith("data: "):
                        continue
                    ev = json.loads(line[6:])
                    events.append(ev)
                    if ev["type"] == "done":
                        break
        finally:
            httpd.shutdown()
            httpd.server_close()
        hello = next(e for e in events if e["type"] == "hello")
        self.assertEqual(hello["profile"], "loose")
        dets = [e for e in events if e["type"] == "detection"]
        self.assertTrue(dets)
        self.assertTrue(any("string" in e and "fret" in e for e in dets), dets[:3])
        verdicts = [e for e in events if e["type"] == "verdict"]
        self.assertTrue(any(e.get("string") in (6, 5, 4, 3) for e in verdicts), verdicts)


class TestShiftString(unittest.TestCase):
    def test_minus_one_moves_open_notes_to_thicker_string(self):
        score = builtin_score()
        ov = string_overrides(score, -1)
        # low E (string 6) cannot go thicker; every other open note can
        for i, n in enumerate(score.notes):
            if n.string == 6:
                self.assertNotIn(i, ov)
            else:
                self.assertEqual(ov[i], n.string + 1)
                self.assertIsNotNone(fret_from_string_midi(ov[i], n.midi))
                self.assertGreaterEqual(fret_from_string_midi(ov[i], n.midi), 4)

    def test_plus_one_is_a_no_op_on_open_strings(self):
        score = builtin_score()
        self.assertEqual(string_overrides(score, 1), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
