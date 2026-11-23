"""Evaluation: the metrics pinned on small fixed examples, the reference check, scoring and its routes."""
import unittest

from stt_api.evaluation import metrics
from stt_api.evaluation import reference
from stt_api.evaluation import scoring
from tests.fakes import FID, FID2, V1, V2, GEMINI, FakeStore, FakeGpu, stored_file, call



def timed_version(words, vid=V1, setup=None, run_seconds=2.0, diarization=True):
    """words: [(speaker, text, start, end)] -> a stored-version dict in the GPU answer shape."""
    notes = [{"type": "word_info", "text": t, "speaker": spk, "start_offset": f"{a:.3f}s", "end_offset": f"{b:.3f}s"}
             for spk, t, a, b in words]
    return {"id": vid, "file_id": FID, "created": vid, "label": "", "image_tag": "0.1.4", "run_seconds": run_seconds,
            "settings": {"language_codes": [], "diarization": diarization}, **({"setup": setup} if setup else {}),
            "response": {"output_text": " ".join(w[1] for w in words), "audio_seconds": 10.0,
                         "steps": [{"type": "model_output", "content": [{"type": "text", "annotations": notes}]}]}}


def slow_distance(a, b):
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1]


REF = {"language": "en", "turns": [{"speaker": "Alice", "start": "00:00:00.0", "end": "00:00:04.0",
                                    "text": "Hello, this is Alice."},
                                   {"speaker": "Bob", "start": 4.0, "end": "8s", "text": "Hi Alice, I'm Bob."}]}
SETUP = {"asr": "Qwen3-ASR-1.7B", "aligner": "Qwen3-ForcedAligner-0.6B",
         "diarization": "pyannote/speaker-diarization-community-1", "image_tag": "0.1.4"}


class EvalTest(unittest.TestCase):
    def test_norm_words(self):
        self.assertEqual(metrics.norm_words("  Don't STOP, Bob!  It’s  well-known. "),
                         ["dont", "stop", "bob", "its", "well", "known"])

    def test_seconds(self):
        for v, want in ((12.5, 12.5), (3, 3.0), ("12.5", 12.5), ("12.5s", 12.5), ("01:02.5", 62.5),
                        ("01:00:02.5", 3602.5)):
            self.assertEqual(reference.seconds(v), want, v)
        for v in ("x", "", "-1", "nan", "inf", "1:2:3:4", True, None, [1]):
            self.assertRaises(ValueError, reference.seconds, v)

    def test_edit_distance_matches_the_table(self):
        import random
        rnd = random.Random(7)
        for _ in range(300):
            a = [rnd.choice("abcd") for _ in range(rnd.randint(0, 70))]
            b = [rnd.choice("abcd") for _ in range(rnd.randint(0, 70))]
            self.assertEqual(metrics.edit_distance(a, b), slow_distance(a, b), (a, b))

    def test_wer(self):
        ref = "the cat sat on the mat".split()
        # 1 substitution (sat -> sit), 1 deletion (the), 1 insertion (big): 3 errors / 6 words
        self.assertEqual(metrics.edit_distance(ref, "the cat sit on mat big".split()) / len(ref), 0.5)
        self.assertEqual(metrics.edit_distance(ref, ref), 0)

    def test_assign_is_optimal(self):
        import itertools, random
        rnd = random.Random(3)
        for n in range(1, 7):
            for _ in range(20):
                m = [[rnd.randint(0, 9) for _ in range(n)] for _ in range(n)]
                cols = metrics.assign(m)
                self.assertEqual(sorted(cols), list(range(n)))
                self.assertEqual(sum(m[i][c] for i, c in enumerate(cols)),
                                 min(sum(m[i][p[i]] for i in range(n)) for p in itertools.permutations(range(n))))

    def test_cpwer_swapped_labels(self):
        ref = [("Alice", "hello this is alice".split()), ("Bob", "hi alice im bob".split()),
               ("Alice", "bye".split())]
        # the model calls Alice spk_2 and Bob spk_1: labels are free, so the score is still 0
        hyp = [("spk_2", "hello this is alice".split()), ("spk_1", "hi alice im bob".split()), ("spk_2", ["bye"])]
        self.assertEqual(metrics.cp_wer(ref, hyp), (0.0, {"spk_2": "Alice", "spk_1": "Bob"}))
        # 1 word with the wrong speaker: a deletion for Alice and an insertion for Bob = 2 errors / 9 words.
        # WER over all words is 0: only cpWER sees the speaker error.
        wrong = [("spk_2", "hello this is alice".split()), ("spk_1", "hi alice im bob bye".split())]
        cp, pairs = metrics.cp_wer(ref, wrong)
        self.assertAlmostEqual(cp, 2 / 9)
        self.assertEqual(pairs, {"spk_2": "Alice", "spk_1": "Bob"})
        # 1 speaker found for 2: Bob's 4 words are all deletions
        self.assertAlmostEqual(metrics.cp_wer(ref, [("spk_1", "hello this is alice bye".split())])[0], 4 / 9)
        # 3 speakers found for 2: the extra speaker's words are insertions
        cp, pairs = metrics.cp_wer(ref, hyp + [("spk_3", ["um"])])
        self.assertAlmostEqual(cp, 1 / 9)
        self.assertNotIn("spk_3", pairs)

    def test_der_collar(self):
        ref = [("A", 0.0, 4.0), ("B", 4.0, 8.0)]
        self.assertEqual(metrics.der(ref, [("x", 0.0, 4.0), ("y", 4.0, 8.0)])["der"], 0)  # labels are free
        # the turn change is 0.2 s late: inside the 0.25 s collar, so no error
        self.assertEqual(metrics.der(ref, [("x", 0.0, 4.2), ("y", 4.2, 8.0)])["der"], 0)
        self.assertGreater(metrics.der(ref, [("x", 0.0, 4.2), ("y", 4.2, 8.0)], collar=0)["der"], 0)
        # 1 s late: frames 4.25-5.0 s (0.75 s) have the wrong speaker. Scored ref time: 8 - 3 collars * 0.5 s
        # minus 0.25 s at each file end = 8 - 0.25 - 0.5 - 0.25 = 7.0 s
        d = metrics.der(ref, [("x", 0.0, 5.0), ("y", 5.0, 8.0)])
        self.assertAlmostEqual(d["confusion"], 0.75 / 7.0)
        self.assertEqual((d["missed"], d["false_alarm"]), (0, 0))
        # B not found at all, and 2 s of false alarm after the end
        d = metrics.der(ref, [("x", 0.0, 4.0), ("x", 8.0, 10.0)])
        self.assertAlmostEqual(d["missed"], 3.5 / 7.0)
        self.assertAlmostEqual(d["false_alarm"], 1.75 / 7.0)  # 8.25-10 s; 8.0-8.25 s is in the collar
        self.assertAlmostEqual(d["der"], 5.25 / 7.0)

    def test_check_reference(self):
        ok = reference.check_reference({"turns": [{"speaker": " Alice ", "text": "Hi", "extra": 1}]})
        self.assertEqual(ok, {"language": "", "turns": [{"speaker": "Alice", "text": "Hi"}]})
        self.assertEqual(reference.check_reference(REF)["turns"][1], REF["turns"][1])
        for body in (None, [], {}, {"turns": []}, {"turns": [{"speaker": "", "text": "x"}]},
                     {"turns": [{"speaker": "A", "text": 1}]}, {"turns": [{"speaker": "A", "text": "x", "start": 1}]},
                     {"turns": [{"speaker": "A", "text": "x", "start": 2, "end": 1}]},
                     {"turns": [{"speaker": "A", "text": "x", "start": "a", "end": 1}]},
                     {"turns": [{"speaker": "A", "text": "?!"}]}, {"language": 5, "turns": [{"speaker": "A", "text": "x"}]},
                     {"turns": [{"speaker": "A" * 41, "text": "x"}]}):
            self.assertRaises(ValueError, reference.check_reference, body)

    def test_score(self):
        v = timed_version([("spk_2", "Hello,", 0.1, 0.5), ("spk_2", "this", 0.6, 1.0), ("spk_2", "is", 1.1, 1.4),
                           ("spk_2", "Alice.", 1.5, 3.9), ("spk_1", "Hi", 4.1, 4.5), ("spk_1", "Alice,", 4.6, 5.0),
                           ("spk_1", "I'm", 5.1, 5.5), ("spk_1", "Rob.", 5.6, 7.9)], setup=SETUP)
        s = scoring.score(REF, v)
        self.assertEqual((s["wer"], s["cpwer"]), (1 / 8, 1 / 8))  # Bob -> Rob
        self.assertEqual(s["mapping"], {"spk_2": "Alice", "spk_1": "Bob"})
        self.assertEqual((s["ref_words"], s["ref_speakers"], s["hyp_speakers"], s["speed"]), (8, 2, 2, 5.0))
        self.assertLess(s["der"]["der"], 0.1)
        self.assertEqual(s["setup"], "Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B + "
                                     "pyannote/speaker-diarization-community-1 @ 0.1.4")
        # no times in the reference: no DER; an old version without setup: "unknown"
        untimed = {"turns": [{"speaker": t["speaker"], "text": t["text"]} for t in REF["turns"]]}
        v.pop("setup")
        s = scoring.score(untimed, v)
        self.assertEqual((s["der"], s["setup"]), (None, "unknown"))
        # a version without annotations: output_text only, 1 speaker ""
        s = scoring.score(REF, {"id": V1, "response": {"output_text": "Hello this is Alice hi Alice im Bob"}})
        self.assertEqual((s["wer"], s["der"], s["hyp_speakers"], s["speed"]), (0, None, 0, None))
        self.assertEqual(s["cpwer"], 1.0)  # Alice gets 4 insertions, Bob 4 deletions

    def test_reference_routes(self):
        store = FakeStore()
        stored_file(store)
        path = f"/v1beta/files/{FID}/reference"
        self.assertEqual(call("GET", path, None, store)[0], 404)
        self.assertEqual(call("PUT", path, {"turns": []}, store)[0], 400)
        code, a = call("PUT", path, REF, store)
        self.assertEqual((code, a), (200, REF))
        self.assertIn(("write", f"files/{FID}/reference.json", True), store.calls)
        self.assertEqual(call("GET", path, None, store), (200, REF))
        self.assertTrue(call("GET", "/v1beta/files", None, store)[1]["files"][0]["reference"])
        self.assertEqual(call("PUT", f"/v1beta/files/{FID2}/reference", REF, store)[0], 404)  # no audio

    def test_score_routes(self):
        store = FakeStore()
        stored_file(store)
        stored_file(store, FID2)
        good = timed_version([("spk_1", w, i, i + 0.9) for i, w in enumerate("hello this is alice".split())]
                             + [("spk_2", w, 4 + i, 4.9 + i) for i, w in enumerate("hi alice im bob".split())],
                             V1, SETUP)
        old = timed_version([("spk_1", w, i, i + 0.9) for i, w in enumerate("hello this is alice hi alice im bob".split())],
                            V2)
        store.put(f"files/{FID}/versions/{V1}.json", good)
        store.put(f"files/{FID}/versions/{V2}.json", old)
        store.put(f"files/{FID2}/versions/{V1}.json", good)  # FID2 has no reference: not scored
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/{V1}/score", None, store)[0], 404)
        call("PUT", f"/v1beta/files/{FID}/reference", REF, store)
        code, s = call("GET", f"/v1beta/files/{FID}/versions/{V1}/score", None, store)
        self.assertEqual((code, s["cpwer"], s["version_id"]), (200, 0, V1))
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/20261121T104512Z-ffff/score", None, store)[0], 404)
        self.assertEqual(call("POST", f"/v1beta/files/{FID}/versions/{V1}/score", None, store)[0], 404)
        code, a = call("GET", "/v1beta/scores", None, store)
        self.assertEqual(code, 200)
        self.assertEqual(sorted((r["file_id"], r["version_id"]) for r in a["rows"]), [(FID, V1), (FID, V2)])
        self.assertEqual(a["rows"][0]["file_name"], "a.mp3")
        by = {g["setup"]: g for g in a["setups"]}
        self.assertEqual(set(by), {"unknown", scoring.setup_label(good)})
        self.assertEqual((by["unknown"]["versions"], by["unknown"]["files"], by["unknown"]["cpwer"]), (1, 1, 1.0))
        self.assertEqual(by[scoring.setup_label(good)]["cpwer"], 0)

    def test_transcribe_saves_setup(self):
        store = FakeStore()
        stored_file(store)
        code, v = call("POST", f"/v1beta/files/{FID}/transcribe", {}, store, FakeGpu(body={**GEMINI, "setup": SETUP}))
        self.assertEqual((code, v["setup"]), (201, SETUP))
        self.assertIsNone(call("POST", f"/v1beta/files/{FID}/transcribe", {}, store)[1]["setup"])

    def test_setup_label_platform(self):
        base = {"asr": "A", "aligner": "B", "diarization": "C", "image_tag": "1"}
        self.assertEqual(scoring.setup_label({"setup": base}), "A + B + C @ 1")
        self.assertEqual(scoring.setup_label({"setup": {**base, "platform": "runpod", "gpu": "NVIDIA RTX A5000"}}),
                         "A + B + C @ 1 on runpod NVIDIA RTX A5000")
        self.assertEqual(scoring.setup_label({"setup": {**base, "platform": "vertex", "gpu": ""}}), "A + B + C @ 1 on vertex")

    def test_group_key(self):
        row = {"setup": "S", "settings": {"diarization": False, "language_codes": ["en"]}}
        self.assertEqual(scoring.group_key(row), "S · no diarization · language en")
