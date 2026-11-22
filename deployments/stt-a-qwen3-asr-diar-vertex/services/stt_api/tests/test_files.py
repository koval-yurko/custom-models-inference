"""Uploads and history: request checks and helpers."""
import unittest
from datetime import datetime, timezone

from stt_api import bucket
from stt_api import files
from tests.fakes import FID


class FilesTest(unittest.TestCase):
    def test_upload_rejects(self):
        ok = {"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 12}
        for body in ({**ok, "size_bytes": 0}, {**ok, "size_bytes": 500_000_001}, {**ok, "size_bytes": "12"},
                     {**ok, "size_bytes": True}, {**ok, "mime_type": "video/mp4"}, {"name": "a", "size_bytes": 12},
                     {"mime_type": "audio/mpeg", "size_bytes": 12}, {**ok, "name": "x" * 201}, {**ok, "name": 5},
                     {**ok, "name": ""}, []):
            with self.assertRaises(ValueError, msg=body):
                files.check_request(body)

    def test_check_ok(self):
        self.assertEqual(files.check_request({"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 123}),
                         ("a.mp3", "audio/mpeg", 123))

    def test_answer(self):
        a = files.answer("B", FID, "audio/mpeg", 123, "https://u")
        self.assertEqual(a, {"id": FID, "upload_url": "https://u", "method": "PUT",
                             "headers": {"Content-Type": "audio/mpeg", "x-goog-content-length-range": "0,123"},
                             "file_uri": f"gs://B/files/{FID}/audio", "expires_in": 900})

    def test_version_id(self):
        vid = files.new_version_id(datetime(2026, 11, 21, 10, 45, 12, tzinfo=timezone.utc), "3fa1")
        self.assertEqual(vid, "20261121T104512Z-3fa1")
        self.assertRegex(vid, bucket.VERSION_RE)

    def test_gpu_request(self):
        body, settings = files.gpu_request("gs://B/files/x/audio", {})
        self.assertEqual(body["input"], [{"type": "file", "file_uri": "gs://B/files/x/audio"}])
        tc = body["generation_config"]["transcription_config"]
        self.assertEqual(tc, {"mode": {"type": "verbatim", "timestamp_granularities": ["word"]}})
        self.assertEqual(settings, {"language_codes": [], "diarization": False})
        body, settings = files.gpu_request("gs://u", {"language_codes": ["en"], "diarization": True})
        tc = body["generation_config"]["transcription_config"]
        self.assertEqual(tc["language_codes"], ["en"])
        self.assertEqual(tc["mode"]["diarization_mode"], "speaker")
        self.assertEqual(settings, {"language_codes": ["en"], "diarization": True})
        for bad in ({"language_codes": "en"}, {"language_codes": [1]}, {"diarization": "yes"}, {"label": "x" * 201},
                    {"label": 5}, []):
            with self.assertRaises(ValueError, msg=bad):
                files.gpu_request("gs://u", bad)
