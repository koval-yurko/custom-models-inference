"""Shared test data and fakes: a dict-backed store, a fake GPU call, and a route() caller."""
import json
from datetime import datetime, timezone

from stt_api import routes

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

    def write(self, name, data, content_type, metadata=None, replace=False):
        self.calls.append(("write", name, replace))
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
    return routes.route(method, path, body, store or FakeStore(), gpu or FakeGpu(), cfg(), lambda: now)
