import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.audio_io import save_wav          # noqa: E402
from guitarcoach.audio_input import FileSource     # noqa: E402
from guitarcoach.ir import Detection, Note, midi_to_freq, midi_to_name  # noqa: E402
from guitarcoach.synth import SR, render           # noqa: E402
from guitarcoach.web import LiveJudge, make_handler  # noqa: E402


def score_of(*midis, step=0.6):
    from guitarcoach.ir import Score
    return Score(title="t", notes=[
        Note(start=i * step, dur=0.5, midi=m, string=3, fret=0)
        for i, m in enumerate(midis)
    ])


class TestLiveJudge(unittest.TestCase):
    def test_hit_advances(self):
        j = LiveJudge(score_of(55, 57).notes)
        out = j.push(Detection(0.01, 55))
        self.assertEqual(out[0]["status"], "hit")
        self.assertEqual(out[0]["index"], 0)
        self.assertEqual(j.hits, 1)

    def test_wrong_pitch_counts_but_advances(self):
        j = LiveJudge(score_of(55).notes)
        out = j.push(Detection(0.02, 56, cents=0))
        self.assertEqual(out[0]["status"], "wrong_pitch")
        self.assertAlmostEqual(out[0]["cents"], 100.0)

    def test_late_detection_marks_gap_as_missed(self):
        j = LiveJudge(score_of(55, 57, 59).notes)
        out = j.push(Detection(1.40, 59))     # first two notes are long gone
        self.assertEqual([v["status"] for v in out], ["missed", "missed", "hit"])

    def test_early_detection_is_ignored(self):
        j = LiveJudge(score_of(55).notes)
        out = j.push(Detection(-0.5, 55))
        self.assertEqual(out, [])
        self.assertEqual(j.judged, 0)

    def test_technique_note_is_skipped_silently(self):
        notes = [Note(start=0.0, dur=0.4, midi=55, tech="bend"),
                 Note(start=0.6, dur=0.4, midi=57)]
        j = LiveJudge(notes)
        out = j.push(Detection(0.62, 57))
        self.assertEqual([v["status"] for v in out], ["skipped", "hit"])
        self.assertEqual(j.judged, 1)          # skipped is not judged


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        events = [(i * 0.5, midi_to_freq(55 + 2 * i), 0.4, i) for i in range(3)]
        audio = render(events, 1.8)
        cls.tmp = tempfile.TemporaryDirectory()
        wav = Path(cls.tmp.name) / "a.wav"
        save_wav(wav, audio, SR)
        cls.score = score_of(55, 57, 59, step=0.5)
        handler = make_handler(cls.score, FileSource(wav), speed=0.0)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def test_serves_page(self):
        c = self.conn()
        c.request("GET", "/")
        r = c.getresponse()
        body = r.read().decode("utf-8")
        self.assertEqual(r.status, 200)
        self.assertIn("guitar-coach", body)
        self.assertIn("后退", body)
        self.assertIn("快进", body)
        c.close()

    def test_query_string_does_not_break_routing(self):
        c = self.conn()
        c.request("GET", "/?auto")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("guitar-coach", r.read().decode("utf-8"))
        c.close()

    def test_serves_score(self):
        c = self.conn()
        c.request("GET", "/score")
        doc = json.loads(c.getresponse().read())
        self.assertEqual(len(doc["notes"]), 3)
        self.assertEqual(doc["notes"][0]["name"], "G3")
        self.assertIn("phrase_id", doc["notes"][0])
        self.assertEqual(doc["tempo"], 80.0)
        self.assertEqual(doc["tuning"], {"1": 64, "2": 59, "3": 55, "4": 50, "5": 45, "6": 40})
        self.assertEqual(doc["defaults"]["mode"], "wait")
        self.assertEqual(doc["defaults"]["speed"], 0.7)
        self.assertEqual(doc["defaults"]["profile"], "loose")
        self.assertIn("input", doc)
        self.assertEqual(doc["meter"], [4, 4])
        self.assertIn("issues", doc)
        c.close()

    def test_event_stream_emits_verdicts(self):
        c = self.conn()
        c.request("GET", "/events?mode=follow")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        kinds, verdicts = [], []
        for _ in range(200):
            line = r.readline().decode()
            if not line:
                break
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            kinds.append(ev["type"])
            if ev["type"] == "verdict":
                verdicts.append(ev)
            if ev["type"] == "done":
                break
        c.close()
        self.assertEqual(kinds[0], "hello")
        self.assertIn("done", kinds)
        self.assertIn("detection", kinds)
        self.assertTrue(verdicts)
        self.assertTrue(all(v["status"] in ("hit", "wrong_pitch", "wrong_string",
                                            "missed", "skipped")
                            for v in verdicts))

    def test_skip_from_marks_skipped_not_missed(self):
        c = self.conn()
        c.request("GET", "/events?from=2&skip_from=0&speed=0&mode=follow")
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        verdicts = []
        for _ in range(200):
            line = r.readline().decode()
            if not line:
                break
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if ev["type"] == "verdict":
                verdicts.append(ev)
            if ev["type"] == "done":
                break
        c.close()
        self.assertGreaterEqual(len(verdicts), 2)
        self.assertEqual(verdicts[0]["status"], "skipped")
        self.assertEqual(verdicts[0]["index"], 0)
        self.assertEqual(verdicts[1]["status"], "skipped")
        self.assertTrue(all(v["status"] != "missed" or v["index"] >= 2
                            for v in verdicts))


if __name__ == "__main__":
    unittest.main(verbosity=2)
