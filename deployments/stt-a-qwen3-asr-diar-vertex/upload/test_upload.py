import io
import json
import http.client
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

import upload

NOW = datetime(2026, 11, 20, 14, 5, 9, tzinfo=timezone.utc)
FID = "0b8e3f6a-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
FID2 = "1c9f4a7b-2d3e-4f60-9bac-1d2e3f4a5b6c"
V1, V2 = "20261120T140509Z-aaaa", "20261121T104512Z-3fa1"
GEMINI = {"output_text": "Hello there.\nHi.", "steps": [{"type": "model_output", "content": [{"type": "text", "annotations": [
    {"type": "word_info", "text": "Hello", "speaker": "spk_1"}, {"type": "word_info", "text": "Hi.", "speaker": "spk_2"},
    {"type": "word_info", "text": "Yes.", "speaker": "spk_1"}]}]}]}


class FakeStore:
    def __init__(self):
        self.objects, self.calls = {}, []

    def put(self, name, data, metadata=None, created="2026-11-20T14:05:09Z"):
        self.objects[name] = (data if isinstance(data, bytes) else json.dumps(data).encode(), metadata or {}, created)

    def list(self, prefix):
        self.calls.append(("list", prefix))
        return [{"name": n, "size": str(len(d)), "metadata": m, "timeCreated": c}
                for n, (d, m, c) in sorted(self.objects.items()) if n.startswith(prefix)]

    def read(self, name):
        self.calls.append(("read", name))
        if name not in self.objects:
            raise KeyError(name)
        return self.objects[name][0]

    def write(self, name, data, content_type, metadata=None):
        self.calls.append(("write", name))
        self.put(name, data, metadata)


class FakeGpu:
    def __init__(self, status=200, body=GEMINI):
        self.status, self.body, self.calls = status, json.dumps(body).encode(), []

    def __call__(self, target, body):
        self.calls.append((target, body))
        return self.status, self.body


def cfg():
    return {"bucket": "B", "sa_email": "sa@p", "image_tag": "0.1.0", "target": "https://v/x:rawPredict",
            "sign": lambda b: b"x"}


def stored_file(store, fid=FID, audio=True, versions=()):
    store.put(f"files/{fid}/meta.json", {"id": fid, "name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 3,
                                         "created": "2026-11-20T14:05:09Z"},
              {"name": "a.mp3", "mime_type": "audio/mpeg", "created": "2026-11-20T14:05:09Z"})
    if audio:
        store.put(f"files/{fid}/audio", b"abc")
    for vid in versions:
        store.put(f"files/{fid}/versions/{vid}.json", {"id": vid, "file_id": fid, "created": vid, "label": "",
                                                        "image_tag": "0.1.0", "settings": {}, "run_seconds": 1.0,
                                                        "response": GEMINI})


def call(method, path, body=None, store=None, gpu=None, now=NOW):
    return upload.route(method, path, body, store or FakeStore(), gpu or FakeGpu(), cfg(), lambda: now)


class UploadTest(unittest.TestCase):
    def test_upload_rejects(self):
        ok = {"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 12}
        for body in ({**ok, "size_bytes": 0}, {**ok, "size_bytes": 500_000_001}, {**ok, "size_bytes": "12"},
                     {**ok, "size_bytes": True}, {**ok, "mime_type": "video/mp4"}, {"name": "a", "size_bytes": 12},
                     {"mime_type": "audio/mpeg", "size_bytes": 12}, {**ok, "name": "x" * 201}, {**ok, "name": 5},
                     {**ok, "name": ""}, []):
            with self.assertRaises(ValueError, msg=body):
                upload.check_request(body)

    def test_check_ok(self):
        self.assertEqual(upload.check_request({"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 123}),
                         ("a.mp3", "audio/mpeg", 123))

    def test_signed_url_shape(self):
        url = upload.signed_put("B", "files/n/audio", "audio/mpeg", 123, "sa@p.iam.gserviceaccount.com", NOW,
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
        upload.signed_put("B", "files/n/audio", "audio/mpeg", 123, "sa@p", NOW, lambda b: seen.append(b) or b"x")
        lines = seen[0].decode().split("\n")
        self.assertEqual(lines[:3], ["GOOG4-RSA-SHA256", "20261120T140509Z", "20261120/auto/storage/goog4_request"])
        self.assertRegex(lines[3], r"^[0-9a-f]{64}$")

    def test_answer(self):
        a = upload.answer("B", FID, "audio/mpeg", 123, "https://u")
        self.assertEqual(a, {"id": FID, "upload_url": "https://u", "method": "PUT",
                             "headers": {"Content-Type": "audio/mpeg", "x-goog-content-length-range": "0,123"},
                             "file_uri": f"gs://B/files/{FID}/audio", "expires_in": 900})

    def test_error_shape(self):
        self.assertEqual(upload.error("x"), {"error": {"code": 400, "message": "x", "status": "INVALID_ARGUMENT"}})

    def test_upload_route_writes_meta(self):
        store = FakeStore()
        code, a = call("POST", "/v1beta/uploads", {"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 3}, store)
        self.assertEqual(code, 200)
        self.assertRegex(a["id"], upload.ID_RE)
        data, meta, _ = store.objects[f"files/{a['id']}/meta.json"]
        self.assertEqual(meta, {"name": "a.mp3", "mime_type": "audio/mpeg", "created": "2026-11-20T14:05:09Z"})
        self.assertEqual(json.loads(data)["size_bytes"], 3)
        self.assertIn(f"/B/files/{a['id']}/audio?", a["upload_url"])

    def test_version_id(self):
        vid = upload.new_version_id(datetime(2026, 11, 21, 10, 45, 12, tzinfo=timezone.utc), "3fa1")
        self.assertEqual(vid, "20261121T104512Z-3fa1")
        self.assertRegex(vid, upload.VERSION_RE)

    def test_gpu_request(self):
        body, settings = upload.gpu_request("gs://B/files/x/audio", {})
        self.assertEqual(body["input"], [{"type": "file", "file_uri": "gs://B/files/x/audio"}])
        tc = body["generation_config"]["transcription_config"]
        self.assertEqual(tc, {"mode": {"type": "verbatim", "timestamp_granularities": ["word"]}})
        self.assertEqual(settings, {"language_codes": [], "diarization": False})
        body, settings = upload.gpu_request("gs://u", {"language_codes": ["en"], "diarization": True})
        tc = body["generation_config"]["transcription_config"]
        self.assertEqual(tc["language_codes"], ["en"])
        self.assertEqual(tc["mode"]["diarization_mode"], "speaker")
        self.assertEqual(settings, {"language_codes": ["en"], "diarization": True})
        for bad in ({"language_codes": "en"}, {"language_codes": [1]}, {"diarization": "yes"}, {"label": "x" * 201},
                    {"label": 5}, []):
            with self.assertRaises(ValueError, msg=bad):
                upload.gpu_request("gs://u", bad)

    def test_list_skips_files_without_audio(self):
        store = FakeStore()
        stored_file(store, FID, versions=(V1, V2))
        stored_file(store, FID2, audio=False)
        code, a = call("GET", "/v1beta/files", None, store)
        self.assertEqual(code, 200)
        self.assertEqual(a["files"], [{"id": FID, "name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 3,
                                       "created": "2026-11-20T14:05:09Z", "versions": 2, "latest": V2}])
        self.assertFalse([c for c in store.calls if c[0] == "read"], "the list must read no object bodies")

    def test_file_versions(self):
        store = FakeStore()
        stored_file(store, versions=(V1, V2))
        code, a = call("GET", f"/v1beta/files/{FID}", None, store)
        self.assertEqual(code, 200)
        self.assertEqual(a["file"]["name"], "a.mp3")
        self.assertEqual([v["id"] for v in a["versions"]], [V2, V1])
        self.assertNotIn("response", a["versions"][0])
        self.assertEqual(a["versions"][0]["text_chars"], len("Hello there.\nHi."))
        self.assertEqual(a["versions"][0]["speakers"], 2)
        self.assertEqual(call("GET", f"/v1beta/files/{FID2}", None, store)[0], 404)
        stored_file(store, FID2, audio=False)  # meta.json but no audio: 404, as in the list and the UI mock
        self.assertEqual(call("GET", f"/v1beta/files/{FID2}", None, store)[0], 404)

    def test_read_version(self):
        store = FakeStore()
        stored_file(store, versions=(V1,))
        code, a = call("GET", f"/v1beta/files/{FID}/versions/{V1}", None, store)
        self.assertEqual((code, a["id"], a["response"]), (200, V1, GEMINI))
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/{V2}", None, store)[0], 404)

    def test_transcribe_saves_version(self):
        store, gpu = FakeStore(), FakeGpu()
        stored_file(store)
        with mock.patch.object(upload.secrets, "token_hex", return_value="3fa1"):
            code, v = call("POST", f"/v1beta/files/{FID}/transcribe", {"label": "t1", "diarization": True}, store, gpu,
                           datetime(2026, 11, 21, 10, 45, 12, tzinfo=timezone.utc))
        self.assertEqual(code, 201)
        self.assertEqual(v["id"], "20261121T104512Z-3fa1")
        saved = json.loads(store.objects[f"files/{FID}/versions/{v['id']}.json"][0])
        self.assertEqual(saved, v)
        self.assertEqual((v["file_id"], v["label"], v["image_tag"], v["created"]),
                         (FID, "t1", "0.1.0", "2026-11-21T10:45:12Z"))
        self.assertEqual(v["settings"], {"language_codes": [], "diarization": True})
        self.assertEqual(v["response"], GEMINI)
        self.assertIsInstance(v["run_seconds"], float)
        target, body = gpu.calls[0]
        self.assertEqual(target, "https://v/x:rawPredict")
        self.assertEqual(body["input"][0]["file_uri"], f"gs://B/files/{FID}/audio")

    def test_gpu_errors_save_nothing(self):
        for status in (429, 500):
            store = FakeStore()
            stored_file(store)
            code, a = call("POST", f"/v1beta/files/{FID}/transcribe", {}, store, FakeGpu(status, {"error": "x"}))
            self.assertEqual(code, status)
            self.assertFalse([n for n in store.objects if "/versions/" in n])

    def test_gpu_answer_not_an_object_saves_nothing(self):
        for body in ([1, 2], "text"):
            store = FakeStore()
            stored_file(store)
            code, a = call("POST", f"/v1beta/files/{FID}/transcribe", {}, store, FakeGpu(200, body))
            self.assertEqual(code, 502, body)
            self.assertFalse([n for n in store.objects if "/versions/" in n])

    def test_transcribe_missing_file(self):
        store, gpu = FakeStore(), FakeGpu()
        stored_file(store, audio=False)
        self.assertEqual(call("POST", f"/v1beta/files/{FID}/transcribe", {}, store, gpu)[0], 404)
        self.assertEqual(gpu.calls, [])

    def test_transcribe_bad_body(self):
        store, gpu = FakeStore(), FakeGpu()
        stored_file(store)
        self.assertEqual(call("POST", f"/v1beta/files/{FID}/transcribe", {"diarization": "x"}, store, gpu)[0], 400)
        self.assertEqual(gpu.calls, [])

    def test_bad_ids_touch_no_store(self):
        store = FakeStore()
        for method, path in (("GET", "/v1beta/files/.."), ("GET", "/v1beta/files/not-a-uuid"),
                             ("GET", f"/v1beta/files/{FID}/versions/x"), ("GET", f"/v1beta/files/{FID}/versions/..%2F"),
                             ("POST", "/v1beta/files/../transcribe"), ("GET", f"/v1beta/files/{FID.upper()}")):
            self.assertEqual(call(method, path, None, store)[0], 400, path)
        self.assertEqual(store.calls, [])

    def test_unknown_route(self):
        self.assertEqual(call("GET", "/v1beta/nope")[0], 404)
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}")[0], 404)

    def test_negative_content_length_400(self):
        server = upload.ThreadingHTTPServer(("127.0.0.1", 0), upload.H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection(*server.server_address, timeout=5)
            conn.putrequest("POST", "/v1beta/uploads")
            conn.putheader("Content-Length", "-1")
            conn.endheaders()
            r = conn.getresponse()
            code, a = r.status, json.loads(r.read())
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(code, 400)
        self.assertIn("negative Content-Length", a["error"]["message"])

    def test_gcs_list_follows_pages(self):
        pages = [{"items": [{"name": "files/a"}], "nextPageToken": "t2"}, {"items": [{"name": "files/b"}]}]
        urls = []

        def fake_open(req, timeout=None):
            urls.append(req.full_url)
            return io.BytesIO(json.dumps(pages[len(urls) - 1]).encode())

        with mock.patch.object(upload.urllib.request, "urlopen", fake_open), mock.patch.object(upload, "token",
                                                                                                return_value="t"):
            items = upload.GcsStore("B").list("files/")
        self.assertEqual([i["name"] for i in items], ["files/a", "files/b"])
        self.assertIn("pageToken=t2", urls[1])


if __name__ == "__main__":
    unittest.main()
