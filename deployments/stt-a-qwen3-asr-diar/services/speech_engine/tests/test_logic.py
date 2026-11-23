import base64
import unittest
from pathlib import Path

from speech_engine.logic import (
    ALIGNER_LANGS, LANGS, WEIGHTS_COPY_ROOT, BadRequest, Job, Turn, Word, build_response, check_duration,
    error_body, estimate_words, fmt_offset, label_speakers, longest_clip, make_turns, parse_request,
    weights_root,
)

B64 = base64.b64encode(b"RIFF....").decode()


def body(item=None, tc=None):
    b = {"input": [item or {"type": "audio", "data": B64, "mime_type": "audio/wav"}]}
    if tc is not None:
        b["generation_config"] = {"transcription_config": tc}
    return b


def lang(codes):
    return parse_request(body(tc={"language_codes": codes}), "B").language


def job(diarize=True, words=True):
    return Job(data=b"x", uri=None, language=None, diarize=diarize, words=words)


class LogicTest(unittest.TestCase):
    def test_language_codes(self):
        self.assertEqual(len(set(LANGS.values())), 30)
        self.assertEqual(lang(["pt-BR"]), "Portuguese")
        self.assertEqual(lang(["zh-HK"]), "Cantonese")
        self.assertEqual(lang(["EN"]), "English")
        self.assertEqual(lang(["fil"]), "Filipino")
        self.assertEqual(lang(["tl"]), "Filipino")
        with self.assertRaises(BadRequest):
            lang(["xx"])
        self.assertIsNone(lang(["en", "de"]))
        self.assertIsNone(lang([]))
        self.assertEqual(len(ALIGNER_LANGS), 11)
        self.assertLessEqual(ALIGNER_LANGS, set(LANGS.values()))

    def test_request_forms(self):
        self.assertEqual(parse_request(body(), "B").data, b"RIFF....")
        for item in ({"type": "audio", "uri": "gs://B/x.wav"}, {"type": "file", "file_uri": "gs://B/x.wav"}):
            j = parse_request(body(item), "B")
            self.assertEqual(j.uri, "gs://B/x.wav")
            self.assertIsNone(j.data)
        signed = "https://storage.googleapis.com/B/files/1/audio?X-Goog-Signature=ab"
        self.assertEqual(parse_request(body({"type": "audio", "uri": signed}), "B").uri, signed)
        bad = [
            body({"type": "file", "file_uri": "gs://other/x.wav"}),
            body({"type": "file", "file_uri": "gs://B/"}),
            body({"type": "file", "file_uri": "https://a/b.wav"}),
            body({"type": "file", "file_uri": "http://storage.googleapis.com/B/x.wav"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com/other/x.wav"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com/B/"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com/B/../other/x.wav"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com/B/%2e%2e/other/x.wav"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com:8443/B/x.wav"}),
            body({"type": "file", "file_uri": "https://u@storage.googleapis.com/B/x.wav"}),
            body({"type": "file", "file_uri": "https://storage.googleapis.com.evil.io/B/x.wav"}),
            {"input": []},
            {"input": [{"type": "audio", "data": B64}, {"type": "audio", "data": B64}]},
            body({"type": "audio", "data": "not base64!!"}),
        ]
        for b in bad:
            with self.assertRaises(BadRequest, msg=b):
                parse_request(b, "B")
        with self.assertRaises(BadRequest):
            parse_request(body(), "B", max_bytes=4)

    def test_weights_root(self):
        vol = "/runpod-volume/stt-a-qwen3-asr-diar"
        self.assertEqual(weights_root({"MODEL": vol, "AIP_STORAGE_URI": "gs://m/x"}), (Path(vol), None))
        self.assertEqual(weights_root({"AIP_STORAGE_URI": "gs://m/x"}), (WEIGHTS_COPY_ROOT, "gs://m/x"))
        self.assertEqual(weights_root({"MODEL": "gs://m/y"}), (WEIGHTS_COPY_ROOT, "gs://m/y"))
        self.assertEqual(weights_root({}), (WEIGHTS_COPY_ROOT, None))

    def test_modes(self):
        j = parse_request(body(), "B")
        self.assertEqual((j.diarize, j.words), (False, False))
        with self.assertRaises(BadRequest):
            parse_request(body(tc={"mode": {"type": "smart", "diarization_mode": "speaker"}}), "B")
        parse_request(body(tc={"mode": {"type": "smart"}}), "B")
        j = parse_request(body(tc={"mode": {"type": "verbatim", "diarization_mode": "speaker",
                                             "timestamp_granularities": ["word"]}}), "B")
        self.assertEqual((j.diarize, j.words), (True, True))
        with self.assertRaises(BadRequest):
            parse_request(body(tc={"custom_vocabulary": ["x"]}), "B")

    def test_wrong_types_are_bad_requests(self):
        bad = [
            {**body(), "generation_config": "x"},
            {**body(), "generation_config": ["x"]},
            body(tc={"mode": 5}),
            body(tc={"mode": ["verbatim"]}),
            body(tc={"mode": {"type": "verbatim", "timestamp_granularities": 5}}),
            body(tc={"language_codes": "en"}),
        ]
        for b in bad:
            with self.assertRaises(BadRequest, msg=b):
                parse_request(b, "B")

    def test_duration_limit(self):
        check_duration(1800.0)
        with self.assertRaises(BadRequest):
            check_duration(1800.1)

    def test_make_turns(self):
        segs = [(0, 2, "A"), (2.5, 4, "A"), (6, 7, "B"), (7.05, 7.2, "A")]
        self.assertEqual(make_turns(segs, 8, True), [Turn(0, 4, "A"), Turn(6, 7, "B")])
        # 180 s split (aligner limit of qwen-asr, plan Task 1 ruling)
        self.assertEqual(make_turns([(0, 700, "A")], 700, True),
                         [Turn(0, 175, "A"), Turn(175, 350, "A"), Turn(350, 525, "A"), Turn(525, 700, "A")])
        self.assertEqual(make_turns([], 650, False),
                         [Turn(0, 162.5, None), Turn(162.5, 325, None), Turn(325, 487.5, None), Turn(487.5, 650, None)])

    def test_no_turns(self):
        self.assertEqual(make_turns([], 5.0, True), [])
        r = build_response([], [], [], {}, job())
        self.assertEqual(r["output_text"], "")
        self.assertNotIn("annotations", r["steps"][0]["content"][0])

    def test_longest_clip(self):
        self.assertEqual(longest_clip([Turn(0, 10, "A"), Turn(20, 70, "B")]), (20, 50))

    def test_estimate_words(self):
        self.assertEqual(estimate_words("ab abcd", 1.0, 2.2), [Word("ab", 1.0, 1.4), Word("abcd", 1.4, 2.2)])
        self.assertEqual(estimate_words("   ", 0, 1), [])

    def test_empty_turn_text(self):
        turns = [Turn(0, 1, "A"), Turn(1, 2, "B")]
        r = build_response(turns, ["", "Hi."], [[], [Word("Hi.", 1.0, 1.5)]], {"A": "spk_1", "B": "spk_2"}, job())
        self.assertEqual(r["output_text"], "Hi.")
        self.assertEqual(len(r["steps"][0]["content"][0]["annotations"]), 1)

    def test_labels(self):
        turns = [Turn(0, 1, "B"), Turn(1, 2, "A"), Turn(2, 3, "B")]
        self.assertEqual(label_speakers(turns), {"B": "spk_1", "A": "spk_2"})

    def test_response_shape(self):
        turns = [Turn(0, 1, "A"), Turn(1, 2, "B")]
        words = [[Word("Hello", 0.1, 0.4), Word("there.", 0.4, 0.8)], [Word("Hi.", 1.0, 1.2)]]
        labels = {"A": "spk_1", "B": "spk_2"}
        r = build_response(turns, ["Hello there.", "Hi."], words, labels, job())
        self.assertEqual(r["output_text"], "Hello there.\nHi.")
        self.assertEqual(r["status"], "completed")
        self.assertEqual(r["steps"][0]["type"], "model_output")
        c = r["steps"][0]["content"][0]
        self.assertEqual(c["type"], "text")
        self.assertEqual(c["text"], "Hello there.\nHi.")
        self.assertEqual(c["annotations"][0], {"type": "word_info", "text": "Hello", "speaker": "spk_1",
                                               "start_offset": "0.100s", "end_offset": "0.400s"})
        self.assertEqual(c["annotations"][2]["speaker"], "spk_2")
        r = build_response(turns, ["Hello there.", "Hi."], words, {}, job(diarize=False))
        self.assertNotIn("speaker", r["steps"][0]["content"][0]["annotations"][0])
        r = build_response(turns, ["Hello there.", "Hi."], words, labels, job(False, False))
        self.assertNotIn("annotations", r["steps"][0]["content"][0])
        self.assertEqual(fmt_offset(1.5), "1.500s")

    def test_error_body(self):
        self.assertEqual(error_body("x"), {"error": {"code": 400, "message": "x", "status": "INVALID_ARGUMENT"}})
        self.assertEqual(error_body("x", 500)["error"]["status"], "INTERNAL")
        self.assertEqual(error_body("x", 503)["error"]["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
