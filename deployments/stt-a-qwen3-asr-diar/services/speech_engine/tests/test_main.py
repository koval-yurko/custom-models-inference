import base64
import contextlib
import io
import shutil
import struct
import threading
import time
import unittest
import wave
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from speech_engine import main, pipeline
from speech_engine.logic import Word

SR = 16000
B64 = base64.b64encode(b"audio").decode()
DIAR = {"mode": {"type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]}}


def body(tc=DIAR):
    return {"input": [{"type": "audio", "data": B64, "mime_type": "audio/wav"}],
            "generation_config": {"transcription_config": tc}}


class FakeModels:
    def __init__(self, texts=("Hello there.", "Hi."), detected="English", align_error=False):
        self.texts, self.detected, self.align_error = list(texts), detected, align_error
        self.transcribe_calls, self.align_calls = [], []

    def diarize(self, audio, sr):
        return [(0.0, 4.0, "A"), (5.0, 9.0, "B")]

    def transcribe(self, clips, sr, language):
        self.transcribe_calls.append((len(clips), max(len(c) / sr for c in clips), language))
        if len(clips) == 1 and language is None:
            return [("Hello there.", self.detected)]
        return [(t, language or self.detected) for t in self.texts[:len(clips)]]

    def align(self, clip, sr, text, language):
        self.align_calls.append(text)
        if self.align_error:
            raise RuntimeError("aligner failed")
        return [Word(w, 0.1 * i, 0.1 * i + 0.1) for i, w in enumerate(text.split())]

    def read_audio(self, uri):
        return b"audio"


@contextlib.contextmanager
def ready_client(models):
    with mock.patch.object(pipeline, "decode", return_value=(np.zeros(10 * SR, np.float32), SR)):
        with TestClient(main.create_app(lambda: models, "B")) as c:
            for _ in range(100):
                if c.get("/health").status_code == 200:
                    break
                time.sleep(0.05)
            yield c


def words(resp):
    return resp.json()["steps"][0]["content"][0].get("annotations", [])


class MainTest(unittest.TestCase):
    def test_not_ready_503(self):
        gate = threading.Event()

        def load():
            gate.wait(5)
            return FakeModels()

        with TestClient(main.create_app(load, "B")) as c:
            self.assertEqual(c.get("/health").status_code, 503)
            r = c.post("/v1beta/interactions", json=body())
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["error"]["status"], "UNAVAILABLE")
            gate.set()

    def test_ready_prints_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), ready_client(FakeModels()) as c:
            self.assertEqual(c.get("/health").status_code, 200)
        self.assertIn("models ready", out.getvalue())

    def test_transcribe_two_speakers(self):
        with ready_client(FakeModels()) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["output_text"], "Hello there.\nHi.")
        self.assertEqual({w["speaker"] for w in words(r)}, {"spk_1", "spk_2"})
        self.assertEqual(words(r)[2]["start_offset"], "5.000s")  # aligner time + turn start
        self.assertEqual(r.json()["audio_seconds"], 10.0)

    def test_answer_has_setup(self):
        setup = {"asr": "A", "aligner": "B", "diarization": "C", "image_tag": "9", "platform": "runpod"}
        m = FakeModels()
        m.gpu = "NVIDIA RTX A5000"
        with mock.patch.object(main, "SETUP", setup), ready_client(m) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(r.json()["setup"], {**setup, "gpu": "NVIDIA RTX A5000"})

    def test_port(self):
        self.assertEqual(main.port({"PORT": "8000", "AIP_HTTP_PORT": "8080"}), 8000)
        self.assertEqual(main.port({"AIP_HTTP_PORT": "9000"}), 9000)
        self.assertEqual(main.port({}), 8080)

    def test_language_detected_once(self):
        m = FakeModels()
        with ready_client(m) as c:
            c.post("/v1beta/interactions", json=body())
        self.assertEqual(len(m.transcribe_calls), 2)
        n, longest, lang = m.transcribe_calls[0]
        self.assertEqual((n, lang), (1, None))
        self.assertLessEqual(longest, 30)
        self.assertEqual(m.transcribe_calls[1][0::2], (2, "English"))

    def test_given_language_skips_detection(self):
        m = FakeModels()
        with ready_client(m) as c:
            c.post("/v1beta/interactions", json=body({**DIAR, "language_codes": ["de-DE"]}))
        self.assertEqual([x[2] for x in m.transcribe_calls], ["German"])

    def test_non_aligner_language_estimates(self):
        m = FakeModels(texts=("สวัสดี ครับ", "ดี"), detected="Thai")
        with ready_client(m) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(m.align_calls, [])
        for w in words(r):
            start, end = float(w["start_offset"][:-1]), float(w["end_offset"][:-1])
            self.assertTrue((0 <= start <= end <= 4) or (5 <= start <= end <= 9), w)

    def test_mixed_detected_language(self):
        m = FakeModels(detected="Chinese,English")
        with ready_client(m) as c:
            c.post("/v1beta/interactions", json=body())
        self.assertEqual(m.transcribe_calls[1][2], "Chinese")

    def test_empty_text_skips_aligner(self):
        m = FakeModels(texts=("", "Hi."))
        with ready_client(m) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(m.align_calls, ["Hi."])
        self.assertEqual(r.json()["output_text"], "Hi.")

    def test_aligner_failure_falls_back(self):
        with ready_client(FakeModels(align_error=True)) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(words(r)[0], {"type": "word_info", "text": "Hello", "speaker": "spk_1",
                                       "start_offset": "0.000s", "end_offset": "1.818s"})

    def test_no_annotations_skips_aligner(self):
        m = FakeModels()
        with ready_client(m) as c:
            r = c.post("/v1beta/interactions", json=body({"mode": "verbatim"}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(m.align_calls, [])
        self.assertEqual(words(r), [])

    def test_internal_error_is_generic(self):
        m = FakeModels()
        m.diarize = mock.Mock(side_effect=RuntimeError("secret detail"))
        with contextlib.redirect_stderr(io.StringIO()) as err, ready_client(m) as c:
            r = c.post("/v1beta/interactions", json=body())
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["error"]["message"], "internal error")
        self.assertIn("secret detail", err.getvalue())

    def test_bad_request(self):
        with ready_client(FakeModels()) as c:
            r = c.post("/v1beta/interactions", json=body({"mode": {"type": "smart", "diarization_mode": "speaker"}}))
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"]["status"], "INVALID_ARGUMENT")
            r = c.post("/v1beta/interactions", content=b"not json", headers={"content-type": "application/json"})
            self.assertEqual(r.status_code, 400)

    @unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg is not installed")
    def test_decode_wav(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(2), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(struct.pack("<2h", 1000, 1000) * 8000)
        audio, sr = pipeline.decode(buf.getvalue())
        self.assertEqual(sr, 16000)
        self.assertAlmostEqual(len(audio) / sr, 1.0, delta=0.01)
        audio, sr = pipeline.decode(buf.getvalue(), max_seconds=0.5)  # -t stops the decode early
        self.assertAlmostEqual(len(audio) / sr, 0.5, delta=0.01)
        with self.assertRaises(pipeline.BadRequest):
            pipeline.decode(b"not audio")


if __name__ == "__main__":
    unittest.main()
