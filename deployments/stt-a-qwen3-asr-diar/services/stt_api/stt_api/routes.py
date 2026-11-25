"""The route table of the STT API service. Every path can start with a platform id (/runpod/v1beta/...): it picks the
GPU platform of "transcribe". A path without one uses the default platform (the first in cfg["platforms"]). route() maps (method, path, body) to (HTTP status, JSON answer).
Ids are checked before any store call. The store, the GPU call and the clock come in as arguments, so tests use fakes.

  POST /v1beta/uploads                                  signed PUT URL for gs://$AUDIO_BUCKET/files/<id>/audio
  GET  /v1beta/files                                    all files that have audio
  GET  /v1beta/files/<id>                               1 file and its version summaries
  GET  /v1beta/files/<id>/versions/<version_id>         1 full version
  POST /v1beta/files/<id>/transcribe                    GPU call through the CORS proxy, then save a new version
  PUT  /v1beta/files/<id>/versions/<version_id>/names   speaker names of 1 version ({"spk_1": "Alice"})
  GET  /v1beta/files/<id>/audio                         signed GET URL of the audio (playback in the browser)
  PUT  /v1beta/files/<id>/reference                     the correct transcript with speakers (replaces the old one)
  GET  /v1beta/files/<id>/reference                     the stored reference
  GET  /v1beta/files/<id>/versions/<version_id>/score   WER, cpWER, DER of 1 version against the reference
  GET  /v1beta/scores                                   scores of all versions of all files with a reference, per setup
  DELETE /v1beta/files/<id>                             the file: audio, versions, names, reference
  DELETE /v1beta/files/<id>/versions/<version_id>       1 version and its names
  DELETE /v1beta/files/<id>/reference                   the reference (the file has no scores after it)
"""
import json
import secrets
import time
import uuid

from stt_api.bucket import ID_RE, NAMES, REFERENCE, VERSION_RE
from stt_api.evaluation.reference import check_reference
from stt_api.evaluation.scoring import all_scores, score
from stt_api.files import (
    answer, check_names, check_request, gpu_request, iso, list_files, new_version_id, summary,
)
from stt_api.gcp import EXPIRES, signed_get, signed_put


def error(message, code=400):
    status = {400: "INVALID_ARGUMENT", 404: "NOT_FOUND"}.get(code, "INTERNAL")
    return {"error": {"code": code, "message": message, "status": status}}


def _json(data):
    try:
        return json.loads(data)
    except ValueError:
        return None


def route(method, path, body, store, gpu, cfg, now):
    """All route logic. Returns (HTTP status, JSON answer). Ids are checked before any store call."""
    parts = path.split("?")[0].strip("/").split("/")
    platform = parts.pop(0) if parts[0] in cfg["platforms"] else cfg["platforms"][0]
    if method == "POST" and parts == ["v1beta", "uploads"]:
        try:
            name, mime, size = check_request(body)
        except ValueError as e:
            return 400, error(str(e))
        fid, t = str(uuid.uuid4()), now()
        meta = {"id": fid, "name": name, "mime_type": mime, "size_bytes": size, "created": iso(t)}
        url = signed_put(cfg["bucket"], f"files/{fid}/audio", mime, size, cfg["sa_email"], t, cfg["sign"])
        store.write(f"files/{fid}/meta.json", json.dumps(meta).encode(), "application/json",
                    {"name": name, "mime_type": mime, "created": meta["created"]})
        return 200, answer(cfg["bucket"], fid, mime, size, url)
    if method == "GET" and parts == ["v1beta", "scores"]:
        return 200, all_scores(store)
    if parts[:2] != ["v1beta", "files"]:
        return 404, error("not found", 404)
    rest = parts[2:]
    if method == "GET" and not rest:
        return 200, {"files": list_files(store.list("files/"))}
    shape = (method, len(rest), rest[1] if len(rest) > 1 else None, rest[3] if len(rest) > 3 else None)
    if shape not in {("GET", 1, None, None), ("POST", 2, "transcribe", None), ("GET", 2, "audio", None),
                     ("GET", 2, "reference", None), ("PUT", 2, "reference", None),
                     ("GET", 3, "versions", None), ("PUT", 4, "versions", "names"), ("GET", 4, "versions", "score"),
                     ("DELETE", 1, None, None), ("DELETE", 2, "reference", None), ("DELETE", 3, "versions", None)}:
        return 404, error("not found", 404)
    fid = rest[0]
    if not ID_RE.match(fid) or (len(rest) >= 3 and not VERSION_RE.match(rest[2])):
        return 400, error("bad file id or version id")
    base = f"files/{fid}/"
    if not any(o["name"] == base + "audio" for o in store.list(base + "audio")):  # as GET /v1beta/files: no audio, no file
        return 404, error("file not found (no audio)", 404)
    if len(rest) == 1 and method == "DELETE":
        # The audio first: without it the file is not in the list, so a stop half way leaves no broken file in the UI.
        for name in sorted((o["name"] for o in store.list(base)), key=lambda n: n != base + "audio"):
            store.delete(name)
        return 200, {"deleted": fid}
    if len(rest) == 1:
        try:
            meta = json.loads(store.read(base + "meta.json"))
        except KeyError:
            return 404, error("file not found", 404)
        vs = [summary(json.loads(store.read(o["name"]))) for o in store.list(base + "versions/")
              if not o["name"].endswith(NAMES)]
        return 200, {"file": meta, "versions": sorted(vs, key=lambda v: v["id"], reverse=True)}
    if rest[1] == "audio":
        try:
            mime = json.loads(store.read(base + "meta.json"))["mime_type"]
        except KeyError:
            return 404, error("file not found", 404)
        url = signed_get(cfg["bucket"], base + "audio", cfg["sa_email"], now(), cfg["sign"])
        return 200, {"url": url, "mime_type": mime, "expires_in": EXPIRES}
    if rest[1] == "reference":
        if method == "GET":
            try:
                return 200, json.loads(store.read(base + REFERENCE))
            except KeyError:
                return 404, error("this file has no reference", 404)
        if method == "DELETE":
            if not store.list(base + REFERENCE):
                return 404, error("this file has no reference", 404)
            store.delete(base + REFERENCE)
            return 200, {"deleted": "reference"}
        try:
            ref = check_reference(body)
        except ValueError as e:
            return 400, error(str(e))
        store.write(base + REFERENCE, json.dumps(ref).encode(), "application/json", replace=True)
        return 200, ref
    if len(rest) >= 3:
        vpath = f"{base}versions/{rest[2]}"
        try:
            version = json.loads(store.read(vpath + ".json"))
        except KeyError:
            return 404, error("version not found", 404)
        if len(rest) == 4 and rest[3] == "score":
            try:
                ref = json.loads(store.read(base + REFERENCE))
            except KeyError:
                return 404, error("this file has no reference", 404)
            return 200, score(ref, version)
        if method == "DELETE":
            store.delete(vpath + ".json")
            store.delete(vpath + NAMES)
            return 200, {"deleted": rest[2]}
        if method == "GET":  # the stored version stays as it is; the names come from their own object
            try:
                version["names"] = json.loads(store.read(vpath + NAMES))
            except KeyError:
                version["names"] = {}
            return 200, version
        try:
            names = check_names(body)
        except ValueError as e:
            return 400, error(str(e))
        store.write(vpath + NAMES, json.dumps(names).encode(), "application/json", replace=True)
        return 200, {"names": names}
    try:
        # A signed URL, not gs://: a GPU service outside GCP (Runpod) has no GCP credentials.
        audio_url = signed_get(cfg["bucket"], base + "audio", cfg["sa_email"], now(), cfg["sign"])
        req, settings = gpu_request(audio_url, body)
    except ValueError as e:
        return 400, error(str(e))
    t, t0 = now(), time.monotonic()
    status, data = gpu(f"{cfg['target']}/{platform}/v1beta/interactions", req)
    if status != 200:
        return status, _json(data) or error(data.decode(errors="replace")[:500], status)
    answer_json = _json(data)
    if not isinstance(answer_json, dict):  # a saved version is never replaced, so it must be readable later
        return 502, error("the GPU answer is not a JSON object", 502)
    version = {"id": new_version_id(t, secrets.token_hex(2)), "file_id": fid, "created": iso(t),
               "label": body.get("label", ""), "image_tag": cfg["image_tag"], "settings": settings,
               "run_seconds": round(time.monotonic() - t0, 1), "setup": answer_json.get("setup"),
               "response": answer_json}
    store.write(f"{base}versions/{version['id']}.json", json.dumps(version).encode(), "application/json")
    return 201, version
