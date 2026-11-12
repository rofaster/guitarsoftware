import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guitarcoach.exercises import builtin_score, g_string_run        # noqa: E402
from guitarcoach.score_io import load_score                          # noqa: E402
from guitarcoach.ir import Detection, Note, Score                    # noqa: E402
from guitarcoach.judge import (LOOSE, STANDARD, JudgeConfig,        # noqa: E402
                               Verdict, summarize)
from guitarcoach.input import choose_profile                        # noqa: E402
from guitarcoach.progress import (advance, annotate_score,           # noqa: E402
                                  phrase_start, prev_bar_start, rewind,
                                  snap_to_bar, snap_to_note)
from guitarcoach.validate import validate_score                      # noqa: E402
from guitarcoach.web import LiveJudge, WaitJudge, _judge_from_input  # noqa: E402


def phrase_notes(*groups, step=0.75):
    notes, i = [], 0
    for pid, midis in enumerate(groups):
        for m in midis:
            notes.append(Note(start=i * step, dur=0.6, midi=m,
                              string=3, fret=0, bar=pid, phrase_id=pid))
            i += 1
    return notes


class TestPhraseNav(unittest.TestCase):
    def setUp(self):
        self.notes = phrase_notes([55, 57, 59, 60], [62, 64, 65, 67])

    def test_phrase_starts(self):
        self.assertEqual(phrase_start(self.notes, 0), 0)
        self.assertEqual(phrase_start(self.notes, 3), 0)
        self.assertEqual(phrase_start(self.notes, 4), 4)
        self.assertEqual(phrase_start(self.notes, 7), 4)

    def test_rewind_goes_to_current_then_previous(self):
        self.assertEqual(rewind(self.notes, 3), 0)
        self.assertEqual(rewind(self.notes, 0), 0)
        self.assertEqual(rewind(self.notes, 6), 4)
        self.assertEqual(rewind(self.notes, 4), 0)

    def test_advance_skips_remaining_of_phrase(self):
        dest, skipped = advance(self.notes, 2)
        self.assertEqual(dest, 4)
        self.assertEqual(skipped, [2, 3])

    def test_snap_to_nearest_start(self):
        # notes at 0, 0.75, 1.5, ...
        self.assertEqual(snap_to_note(self.notes, 0.1), 0)
        self.assertEqual(snap_to_note(self.notes, 1.0), 1)
        self.assertEqual(snap_to_note(self.notes, 1.4), 2)


class TestAutoPhrase(unittest.TestCase):
    def test_splits_every_eight_beats(self):
        # 80 BPM, 8 beats = 6.0 s, so t=6.0 starts phrase 1
        notes = [Note(start=t, dur=0.4, midi=55) for t in (0.0, 3.0, 6.0, 7.0)]
        score = annotate_score(Score(tempo=80, notes=notes))
        self.assertEqual([n.phrase_id for n in score.notes], [0, 0, 1, 1])


class TestBuiltinScore(unittest.TestCase):
    def test_open_strings_is_the_default(self):
        score = builtin_score()
        self.assertEqual(score.title, "空弦练习")
        self.assertEqual(score.tempo, 80.0)
        self.assertEqual(score.meter, (4, 4))
        self.assertEqual(len(score.notes), 16)
        self.assertEqual({n.bar for n in score.notes}, {0, 1, 2, 3})
        self.assertEqual({n.phrase_id for n in score.notes}, {0, 1})
        self.assertTrue(all(n.fret == 0 for n in score.notes))
        self.assertEqual([n.string for n in score.notes],
                         [6, 5, 4, 3, 2, 1, 1, 2, 1, 2, 3, 4, 5, 6, 6, 5])
        starts = [n.start for n in score.notes]
        gaps = [starts[i] - starts[i - 1] for i in range(1, len(starts))]
        self.assertTrue(all(g >= 0.2 for g in gaps))

    def test_matches_json_and_validates(self):
        path = Path(__file__).resolve().parents[1] / "scores" / "open-strings.json"
        disk = load_score(path)
        built = builtin_score()
        self.assertEqual(
            [(n.start, n.midi, n.string, n.fret, n.bar, n.phrase_id) for n in built.notes],
            [(n.start, n.midi, n.string, n.fret, n.bar, n.phrase_id) for n in disk.notes],
        )
        self.assertEqual(validate_score(annotate_score(built)), [])

    def test_g_string_run_still_available(self):
        score = g_string_run()
        self.assertEqual(score.title, "G 弦音阶走句")
        self.assertEqual(len(score.notes), 16)
        self.assertTrue(all(n.string == 3 for n in score.notes))


class TestBarNav(unittest.TestCase):
    def setUp(self):
        self.notes = phrase_notes([55, 57, 59, 60], [62, 64, 65, 67], [69, 71])

    def test_back_current_bar_then_previous(self):
        self.assertEqual(rewind(self.notes, 6), 4)
        self.assertEqual(rewind(self.notes, 4), 0)
        self.assertEqual(rewind(self.notes, 0), 0)

    def test_forward_next_bar_skips_rest(self):
        self.assertEqual(advance(self.notes, 5), (8, [5, 6, 7]))

    def test_prev_bar_start(self):
        self.assertEqual(prev_bar_start(self.notes, 6), 0)
        self.assertEqual(prev_bar_start(self.notes, 9), 4)
        self.assertEqual(prev_bar_start(self.notes, 2), 0)

    def test_scrub_snaps_to_bar_start(self):
        self.assertEqual(snap_to_bar(self.notes, 1.2), 0)
        self.assertEqual(snap_to_bar(self.notes, 2.8), 4)

    def test_auto_bars_from_meter(self):
        notes = [Note(start=t, dur=0.4, midi=55) for t in (0.0, 2.9, 3.0, 6.1)]
        score = annotate_score(Score(tempo=80, notes=notes))   # 4/4 bar = 3.0 s
        self.assertEqual([n.bar for n in score.notes], [0, 0, 1, 2])


class TestAccuracy(unittest.TestCase):
    def test_loose_accuracy_is_hit_over_hit_plus_wrong(self):
        notes = phrase_notes([55, 57, 59, 60, 62])
        v = [Verdict(notes[0], "hit"), Verdict(notes[1], "wrong_pitch"),
             Verdict(notes[2], "missed"), Verdict(notes[3], "skipped"),
             Verdict(notes[4], "hit")]
        s = summarize(v)
        self.assertAlmostEqual(s.pitch_accuracy, 2 / 3)
        self.assertAlmostEqual(s.accuracy_for(LOOSE), 2 / 3)
        self.assertAlmostEqual(s.accuracy_for(STANDARD), 2 / 4)


def wrong(t):
    return Detection(t, 40)          # far off pitch, right on time


class TestRewindPrompt(unittest.TestCase):
    def test_never_holds_and_five_wrong_prompts_once(self):
        notes = phrase_notes(*[[60] * 4] * 3)
        j = LiveJudge(notes)
        events = []
        for k in range(8):
            events += j.push(wrong(k * 0.75))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds.count("verdict"), 8)            # never stops
        prompts = [e for e in events if e["type"] == "suggest_back"]
        # each 4-note bar trips the >50% rule on its 3rd wrong note
        self.assertEqual([p["bar"] for p in prompts], [0, 1])
        self.assertEqual(prompts[0]["target"], 0)
        self.assertEqual(prompts[1]["target"], 0)
        self.assertFalse(hasattr(j, "held"))

    def test_streak_rule_and_reset_by_hit_or_miss(self):
        # one long bar so only the streak rule can fire before bar_rate
        notes = [Note(start=k * 0.75, dur=0.6, midi=60, bar=k // 4 if k < 4 else 1)
                 for k in range(10)]
        j = LiveJudge(notes)
        j.prompted_bar = None
        out = j.push(Detection(0.0, 60))                        # hit
        self.assertEqual(j.pitch_streak, 0)
        out += j.push(wrong(0.75))
        self.assertEqual(j.pitch_streak, 1)
        out += j.push(Detection(1.5, 60))                       # hit resets
        self.assertEqual(j.pitch_streak, 0)
        out += j.push(wrong(2.25))
        out += j.tick(3.0 + 0.4)                                # note 4 missed
        self.assertEqual(j.pitch_streak, 0)

    def test_string_hint_does_not_break_streak(self):
        notes = [Note(start=k * 0.75, dur=0.6, midi=60, string=3, bar=0) for k in range(3)]
        j = LiveJudge(notes)
        j.push(wrong(0.0))
        j.push(Detection(0.75, 60, string=2))                   # wrong_string
        self.assertEqual(j.pitch_streak, 1)

    def test_bar_rate_waits_until_wrong_exceeds_half_of_bar(self):
        notes = [Note(start=k * 0.75, dur=0.6, midi=60, bar=0) for k in range(4)]
        j = LiveJudge(notes)
        out = j.push(wrong(0.0)) + j.push(wrong(0.75))
        self.assertFalse([e for e in out if e["type"] == "suggest_back"])   # 2/4 = 50%
        out = j.push(Detection(1.5, 60)) + j.push(Detection(2.25, 60))
        self.assertFalse([e for e in out if e["type"] == "suggest_back"])
        j = LiveJudge(notes)
        out = j.push(wrong(0.0)) + j.push(wrong(0.75)) + j.push(wrong(1.5))
        prompts = [e for e in out if e["type"] == "suggest_back"]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["reason"], "bar_rate")

    def test_missed_counts_in_denominator_not_as_error(self):
        notes = [Note(start=k * 0.75, dur=0.6, midi=60, bar=0) for k in range(4)]
        j = LiveJudge(notes)
        out = j.tick(1.2)            # notes 0 and 1 missed
        out += j.push(wrong(1.5))    # 1 wrong of 3 -> 33%, no prompt
        self.assertFalse([e for e in out if e["type"] == "suggest_back"])

    def test_no_early_missed(self):
        j = LiveJudge([Note(start=1.0, dur=0.6, midi=60, bar=0)])
        self.assertEqual(j.tick(1.3), [])
        self.assertEqual(j.tick(1.4)[0]["status"], "missed")

    def test_loop_end_stops_judging_past_b(self):
        j = LiveJudge(phrase_notes([55, 57], [59]))
        j.end = 2
        out = j.tick(10.0)
        self.assertEqual([e["index"] for e in out], [0, 1])
        self.assertEqual(j.i, 2)

    def test_live_skip_is_not_missed(self):
        j = LiveJudge(phrase_notes([55, 57, 59, 60], [62]))
        out = j.skip_range(0, 4)
        self.assertEqual([e["status"] for e in out], ["skipped"] * 4)
        self.assertEqual(j.judged, 0)
        self.assertEqual(j.i, 4)


class TestWaitMode(unittest.TestCase):
    def test_wrong_flashes_and_stays_right_advances(self):
        notes = phrase_notes([55, 57])
        j = WaitJudge(notes)
        out = j.push(Detection(99.0, 50))            # time is ignored
        self.assertEqual(out[0]["type"], "flash")
        self.assertEqual(out[0]["index"], 0)
        self.assertEqual(out[0]["cents"], -500.0)
        self.assertEqual(j.i, 0)
        out = j.push(Detection(500.0, 55, cents=60))  # within 80 cents
        self.assertEqual(out[0]["status"], "hit")
        self.assertEqual(j.i, 1)

    def test_never_missed(self):
        j = WaitJudge(phrase_notes([55, 57, 59]))
        out = []
        for t in (10.0, 20.0, 30.0):
            out += j.push(Detection(t, 70))
        self.assertTrue(all(e["type"] == "flash" for e in out))

    def test_wrong_string_flashes_and_stays(self):
        # phrase_notes writes every note on string 3; G3 on string 4 is
        # the same pitch on a thicker string (the open-string drill).
        notes = phrase_notes([55, 57])
        j = WaitJudge(notes)
        out = j.push(Detection(0.1, 55, string=4, fret=5))
        self.assertEqual(out[0]["type"], "flash")
        self.assertEqual(out[0]["status"], "wrong_string")
        self.assertEqual(out[0]["string"], 4)
        self.assertEqual(out[0]["index"], 0)
        self.assertEqual(j.i, 0)
        self.assertEqual(j.hits, 0)
        out = j.push(Detection(0.2, 55, string=3, fret=0))
        self.assertEqual(out[0]["status"], "hit")
        self.assertEqual(j.i, 1)
        self.assertEqual(j.hits, 1)

    def test_pitch_only_still_advances_without_string(self):
        j = WaitJudge(phrase_notes([55]))
        out = j.push(Detection(0.1, 55))          # no string on the detection
        self.assertEqual(out[0]["status"], "hit")
        self.assertEqual(j.i, 1)


class TestValidation(unittest.TestCase):
    def codes(self, notes, **kw):
        return [i.code for i in validate_score(annotate_score(Score(notes=notes, **kw)))]

    def test_flags_without_changing(self):
        notes = [Note(start=0.0, dur=0.75, midi=30, string=3, fret=0)]
        score = annotate_score(Score(notes=notes))
        before = list(score.notes)
        codes = [i.code for i in validate_score(score)]
        self.assertIn("range", codes)
        self.assertIn("mismatch", codes)
        self.assertEqual(score.notes, before)

    def test_bad_position(self):
        self.assertIn("position", self.codes([Note(0.0, 0.75, 60, string=7, fret=0)]))
        self.assertIn("position", self.codes([Note(0.0, 0.75, 60, string=2, fret=25)]))

    def test_tie_across_bar_line(self):
        # 80 BPM: bar = 3.0 s
        self.assertIn("tie", self.codes([Note(2.5, 1.0, 55, string=3, fret=0)]))
        self.assertNotIn("tie", self.codes([Note(2.25, 0.75, 55, string=3, fret=0)]))

    def test_same_string_overlap_unless_legato(self):
        a = Note(0.0, 1.0, 55, string=3, fret=0)
        self.assertIn("same_string", self.codes([a, Note(0.5, 0.5, 57, string=3, fret=2)]))
        self.assertNotIn("same_string",
                         self.codes([a, Note(0.5, 0.5, 57, string=3, fret=2, tech="slide")]))

    def test_bar_closure_detects_overshoot(self):
        notes = [Note(0.0, 1.5, 55, string=4, fret=5), Note(0.75, 1.5, 59, string=3, fret=4)]
        self.assertIn("bar_close", self.codes(notes))

    def test_exact_bar_tolerance(self):
        # four quarters with a tiny rounding error (< 1/32 beat) still close
        notes = [Note(k * 0.75, 0.751, 55 + k, string=None, fret=None) for k in range(4)]
        self.assertNotIn("bar_close", self.codes(notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDegradedInput(unittest.TestCase):
    def test_late_hit_counts_when_onset_is_off(self):
        notes = [Note(start=1.0, dur=0.4, midi=55, bar=0)]
        late = Detection(1.6, 55, cents=5)          # 600 ms late
        tight = LiveJudge(notes, LOOSE)
        self.assertEqual(tight.push(late)[0]["status"], "missed")
        loose = LiveJudge(notes, JudgeConfig(judge_onset=False))
        out = loose.push(late)
        self.assertEqual([e["status"] for e in out], ["hit"])
        self.assertEqual(loose.tick(10.0), [])       # clock must not invent misses

    def test_bluetooth_profile_disables_onset(self):
        p = choose_profile(is_bluetooth=True, latency_ms=180)
        cfg = _judge_from_input(p)
        self.assertFalse(cfg.judge_onset)
        self.assertEqual(cfg.label, "loose")
        self.assertEqual(p.warning_code, "bluetooth_latency")
        self.assertIn("有线", p.warning_zh)

    def test_name_detects_bluetooth(self):
        p = choose_profile(driver="wasapi", latency_ms=40,
                           device_name="AirPods Pro")
        self.assertTrue(p.pitch_only)
        self.assertEqual(p.warning_code, "bluetooth_latency")
