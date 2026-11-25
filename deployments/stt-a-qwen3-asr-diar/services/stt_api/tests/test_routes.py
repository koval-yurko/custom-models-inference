"""The route table: every route against a fake store and a fake GPU."""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from stt_api import bucket
from stt_api import routes
from tests.fakes import FID, FID2, V1, V2, GEMINI, FakeStore, FakeGpu, stored_file, call


class RoutesTest(unittest.TestCase):
    def test_error_shape(self):
        self.assertEqual(routes.error("x"), {"error": {"code": 400, "message": "x", "status": "INVALID_ARGUMENT"}})

    def test_upload_route_writes_meta(self):
        store = FakeStore()
        code, a = call("POST", "/v1beta/uploads", {"name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 3}, store)
        self.assertEqual(code, 200)
        self.assertRegex(a["id"], bucket.ID_RE)
        data, meta, _ = store.objects[f"files/{a['id']}/meta.json"]
        self.assertEqual(meta, {"name": "a.mp3", "mime_type": "audio/mpeg", "created": "2026-11-20T14:05:09Z"})
        self.assertEqual(json.loads(data)["size_bytes"], 3)
        self.assertIn(f"/B/files/{a['id']}/audio?", a["upload_url"])

    def test_list_skips_files_without_audio(self):
        store = FakeStore()
        stored_file(store, FID, versions=(V1, V2))
        stored_file(store, FID2, audio=False)
        code, a = call("GET", "/v1beta/files", None, store)
        self.assertEqual(code, 200)
        self.assertEqual(a["files"], [{"id": FID, "name": "a.mp3", "mime_type": "audio/mpeg", "size_bytes": 3,
                                       "created": "2026-11-20T14:05:09Z", "versions": 2, "latest": V2, "reference": False}])
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
        with mock.patch.object(routes.secrets, "token_hex", return_value="3fa1"):
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
        self.assertEqual(target, "https://proxy/vertex/v1beta/interactions")  # no prefix: the default platform
        uri = body["input"][0]["file_uri"]
        self.assertTrue(uri.startswith(f"https://storage.googleapis.com/B/files/{FID}/audio?"), uri)
        self.assertIn("X-Goog-Signature=", uri)

    def test_platform_prefix(self):
        store, gpu = FakeStore(), FakeGpu()
        stored_file(store, versions=[V1])
        code, _ = call("POST", f"/runpod/v1beta/files/{FID}/transcribe", {}, store, gpu)
        self.assertEqual(code, 201)
        self.assertEqual(gpu.calls[0][0], "https://proxy/runpod/v1beta/interactions")
        # The other routes ignore the platform: the same files on every platform.
        self.assertEqual(call("GET", f"/runpod/v1beta/files/{FID}/versions/{V1}", None, store)[0], 200)
        self.assertEqual(call("GET", "/vertex/v1beta/files", None, store)[0], 200)
        # Only a known platform id is a prefix.
        self.assertEqual(call("GET", "/baseten/v1beta/files", None, store)[0], 404)
        self.assertEqual(call("GET", "/runpod", None, store)[0], 404)

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

    def test_names_saved_per_version(self):
        store = FakeStore()
        stored_file(store, versions=(V1, V2))
        raw = store.objects[f"files/{FID}/versions/{V1}.json"][0]
        code, a = call("PUT", f"/v1beta/files/{FID}/versions/{V1}/names", {"spk_1": " Alice ", "spk_2": "Bob"}, store)
        self.assertEqual((code, a), (200, {"names": {"spk_1": "Alice", "spk_2": "Bob"}}))
        self.assertIn(("write", f"files/{FID}/versions/{V1}.names.json", True), store.calls)
        self.assertEqual(store.objects[f"files/{FID}/versions/{V1}.json"][0], raw, "the version JSON must not change")
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/{V1}", None, store)[1]["names"],
                         {"spk_1": "Alice", "spk_2": "Bob"})
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/{V2}", None, store)[1]["names"], {})
        call("PUT", f"/v1beta/files/{FID}/versions/{V1}/names", {"spk_1": "Ann"}, store)  # replaces the whole map
        self.assertEqual(call("GET", f"/v1beta/files/{FID}/versions/{V1}", None, store)[1]["names"], {"spk_1": "Ann"})
        # the names object is not a version: not in the list count, not in the file versions
        self.assertEqual(call("GET", "/v1beta/files", None, store)[1]["files"][0]["versions"], 2)
        self.assertEqual([v["id"] for v in call("GET", f"/v1beta/files/{FID}", None, store)[1]["versions"]], [V2, V1])

    def test_names_rejects(self):
        store = FakeStore()
        stored_file(store, versions=(V1,))
        path = f"/v1beta/files/{FID}/versions/{V1}/names"
        for body in ({f"spk_{i}": "x" for i in range(9)}, {"spk_1": "x" * 41}, {"spk_1": "  "}, {"spk_1": 5},
                     {"alice": "x"}, {"spk_1/../x": "x"}, ["spk_1"], None):
            self.assertEqual(call("PUT", path, body, store)[0], 400, body)
        self.assertEqual(call("PUT", path, {f"spk_{i}": "x" * 40 for i in range(8)}, store)[0], 200)
        self.assertEqual(call("PUT", f"/v1beta/files/{FID}/versions/{V2}/names", {"spk_1": "A"}, store)[0], 404)
        self.assertEqual(call("PUT", f"/v1beta/files/{FID}/versions/x/names", {}, store)[0], 400)
        self.assertEqual(call("PUT", f"/v1beta/files/{FID}/versions/{V1}", {}, store)[0], 404)
        self.assertFalse([n for n in store.objects if n.endswith(f"{V2}.names.json")])

    def test_audio_url(self):
        store = FakeStore()
        stored_file(store)
        code, a = call("GET", f"/v1beta/files/{FID}/audio", None, store)
        self.assertEqual(code, 200)
        self.assertEqual((a["mime_type"], a["expires_in"]), ("audio/mpeg", 900))
        self.assertTrue(a["url"].startswith(f"https://storage.googleapis.com/B/files/{FID}/audio?"), a["url"])
        self.assertIn("X-Goog-SignedHeaders=host&", a["url"])
        self.assertEqual(call("GET", f"/v1beta/files/{FID2}/audio", None, store)[0], 404)
        self.assertEqual(call("GET", "/v1beta/files/x/audio", None, FakeStore())[0], 400)

    def test_unknown_route(self):
        self.assertEqual(call("GET", "/v1beta/nope")[0], 404)
        self.assertEqual(call("DELETE", "/v1beta/files")[0], 404)
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/audio")[0], 404)
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/versions/{V1}/names")[0], 404)

    def test_delete_version(self):
        store = FakeStore()
        stored_file(store, versions=(V1, V2))
        store.put(f"files/{FID}/versions/{V1}.names.json", {"spk_1": "Ann"})
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/versions/{V1}", None, store), (200, {"deleted": V1}))
        self.assertEqual([n for n in store.objects if "/versions/" in n], [f"files/{FID}/versions/{V2}.json"])
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/versions/{V1}", None, store)[0], 404)
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/versions/x", None, store)[0], 400)

    def test_delete_reference(self):
        store = FakeStore()
        stored_file(store)
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/reference", None, store)[0], 404)
        store.put(f"files/{FID}/reference.json", {"language": "en", "turns": []})
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}/reference", None, store), (200, {"deleted": "reference"}))
        self.assertNotIn(f"files/{FID}/reference.json", store.objects)
        self.assertIn(f"files/{FID}/audio", store.objects)

    def test_delete_file(self):
        store = FakeStore()
        stored_file(store, versions=(V1, V2))
        stored_file(store, FID2, versions=(V1,))
        store.put(f"files/{FID}/reference.json", {"language": "en", "turns": []})
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}", None, store), (200, {"deleted": FID}))
        self.assertFalse([n for n in store.objects if n.startswith(f"files/{FID}/")])
        self.assertTrue([n for n in store.objects if n.startswith(f"files/{FID2}/")], "other files stay")
        deletes = [c[1] for c in store.calls if c[0] == "delete"]
        self.assertEqual(deletes[0], f"files/{FID}/audio", "audio first: a half-deleted file is not in the list")
        self.assertEqual(call("DELETE", f"/v1beta/files/{FID}", None, store)[0], 404)
        self.assertEqual(call("DELETE", "/v1beta/files/not-a-uuid", None, store)[0], 400)
