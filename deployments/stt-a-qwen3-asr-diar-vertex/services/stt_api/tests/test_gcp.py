"""GCS V4 signed URLs and the GCS list call."""
import io
import json
import unittest
from unittest import mock

from stt_api import gcp
from tests.fakes import NOW


class GcpTest(unittest.TestCase):
    def test_signed_url_shape(self):
        url = gcp.signed_put("B", "files/n/audio", "audio/mpeg", 123, "sa@p.iam.gserviceaccount.com", NOW,
                                lambda b: b"x")
        self.assertTrue(url.startswith("https://storage.googleapis.com/B/files/n/audio?"), url)
        for part in ("X-Goog-Algorithm=GOOG4-RSA-SHA256", "X-Goog-Expires=900",
                     "X-Goog-SignedHeaders=content-type%3Bhost%3Bx-goog-content-length-range",
                     "X-Goog-Credential=sa%40p.iam.gserviceaccount.com%2F20261120%2Fauto%2Fstorage%2Fgoog4_request",
                     "X-Goog-Date=20261120T140509Z"):
            self.assertIn(part, url)
        self.assertTrue(url.endswith("&X-Goog-Signature=78"), url)

    def test_string_to_sign(self):
        seen = []
        gcp.signed_put("B", "files/n/audio", "audio/mpeg", 123, "sa@p", NOW, lambda b: seen.append(b) or b"x")
        lines = seen[0].decode().split("\n")
        self.assertEqual(lines[:3], ["GOOG4-RSA-SHA256", "20261120T140509Z", "20261120/auto/storage/goog4_request"])
        self.assertRegex(lines[3], r"^[0-9a-f]{64}$")

    def test_signed_get_canonical(self):
        seen = []
        orig = gcp.hashlib.sha256
        with mock.patch.object(gcp.hashlib, "sha256", lambda b: seen.append(b) or orig(b)):
            gcp.signed_get("B", "files/n/audio", "sa@p", NOW, lambda b: b"x")
        lines = seen[0].decode().split("\n")
        self.assertEqual(lines[0], "GET")
        self.assertEqual(lines[3:], ["host:storage.googleapis.com", "", "host", "UNSIGNED-PAYLOAD"])

    def test_gcs_list_follows_pages(self):
        pages = [{"items": [{"name": "files/a"}], "nextPageToken": "t2"}, {"items": [{"name": "files/b"}]}]
        urls = []

        def fake_open(req, timeout=None):
            urls.append(req.full_url)
            return io.BytesIO(json.dumps(pages[len(urls) - 1]).encode())

        with mock.patch.object(gcp.urllib.request, "urlopen", fake_open), mock.patch.object(gcp, "token",
                                                                                                return_value="t"):
            items = gcp.GcsStore("B").list("files/")
        self.assertEqual([i["name"] for i in items], ["files/a", "files/b"])
        self.assertIn("pageToken=t2", urls[1])
