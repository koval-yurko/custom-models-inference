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


class GpuPostTest(unittest.TestCase):
    def test_id_token_for_the_proxy(self):
        seen = []

        class Resp:
            status = 200

            def __init__(self, data):
                self.data = data

            def read(self):
                return self.data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_open(req, timeout=None):
            seen.append(req)
            return Resp(b"ID-TOKEN" if "identity" in req.full_url else b"{}")

        gcp._ids.clear()
        with mock.patch.object(gcp.urllib.request, "urlopen", fake_open):
            self.assertEqual(gcp.gpu_post("https://proxy.run.app/runpod/v1beta/interactions", {"a": 1}), (200, b"{}"))
            gcp.gpu_post("https://proxy.run.app/vertex/v1beta/interactions", {"a": 1})
        ident = [r for r in seen if "identity" in r.full_url]
        self.assertEqual(len(ident), 1)  # cached for the same audience
        self.assertIn("audience=https%3A%2F%2Fproxy.run.app", ident[0].full_url)
        post = seen[1]
        self.assertEqual(post.full_url, "https://proxy.run.app/runpod/v1beta/interactions")
        self.assertEqual(post.get_header("Authorization"), "Bearer ID-TOKEN")

