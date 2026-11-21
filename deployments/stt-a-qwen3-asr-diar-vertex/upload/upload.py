# STT-A files service. Runs in the stock python image (python3 -u -c <this file>), as the CORS proxy, so it is
# 1 file with the standard library only. Spec: docs/specs/2026-11-21-stt-a-design.md, section "Files service".
#   POST /v1beta/uploads                            signed PUT URL for gs://$AUDIO_BUCKET/files/<id>/audio
#   GET  /v1beta/files                              all files that have audio
#   GET  /v1beta/files/<id>                         1 file and its version summaries
#   GET  /v1beta/files/<id>/versions/<version_id>   1 full version
#   POST /v1beta/files/<id>/transcribe              GPU :rawPredict, then save a new version
# It signs through the IAM Credentials signBlob API with its own service account, so it needs no key file.
import base64, hashlib, json, os, re, secrets, time, traceback, urllib.error, urllib.request, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlencode

AUDIO_TYPES = frozenset({"audio/wav", "audio/mp3", "audio/aiff", "audio/aac", "audio/ogg", "audio/flac", "audio/mpeg",
                         "audio/m4a", "audio/l16", "audio/opus", "audio/alaw", "audio/mulaw", "audio/webm"})
MAX_BYTES = 500_000_000
MAX_TEXT = 200
EXPIRES = 900
GPU_TIMEOUT = 900  # the Vertex AI endpoint stops a request at 600 s (spec fact 10)
HOST = "storage.googleapis.com"
SIGNED = "content-type;host;x-goog-content-length-range"
ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-api-key, authorization",
    "Access-Control-Max-Age": "600",
}
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_tok = {"value": "", "exp": 0.0}


def error(message, code=400):
    status = {400: "INVALID_ARGUMENT", 404: "NOT_FOUND"}.get(code, "INTERNAL")
    return {"error": {"code": code, "message": message, "status": status}}


def _text(value, field, required):
    if not isinstance(value, str) or len(value) > MAX_TEXT or (required and not value):
        raise ValueError(f"{field} must be a string of {1 if required else 0} to {MAX_TEXT} chars")
    return value


def check_request(body):
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    name = _text(body.get("name"), "name", True)
    mime, size = body.get("mime_type"), body.get("size_bytes")
    if mime not in AUDIO_TYPES:
        raise ValueError(f"mime_type must be one of: {', '.join(sorted(AUDIO_TYPES))}")
    if type(size) is not int or not 1 <= size <= MAX_BYTES:
        raise ValueError(f"size_bytes must be an integer from 1 to {MAX_BYTES}")
    return name, mime, size


def signed_put(bucket, name, mime, size, sa_email, now, sign):
    """GCS V4 signing: canonical request -> string to sign -> hex of the RSA signature."""
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    scope = f"{day}/auto/storage/goog4_request"
    query = "&".join(f"{k}={quote(v, safe='-_.~')}" for k, v in sorted({
        "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
        "X-Goog-Credential": f"{sa_email}/{scope}",
        "X-Goog-Date": stamp,
        "X-Goog-Expires": str(EXPIRES),
        "X-Goog-SignedHeaders": SIGNED,
    }.items()))
    path = f"/{bucket}/{quote(name, safe='/-_.~')}"
    canonical = "\n".join(["PUT", path, query, f"content-type:{mime}", f"host:{HOST}",
                           f"x-goog-content-length-range:0,{size}", "", SIGNED, "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["GOOG4-RSA-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    return f"https://{HOST}{path}?{query}&X-Goog-Signature={sign(to_sign.encode()).hex()}"


def answer(bucket, file_id, mime, size, url):
    return {"id": file_id, "upload_url": url, "method": "PUT",
            "headers": {"Content-Type": mime, "x-goog-content-length-range": f"0,{size}"},
            "file_uri": f"gs://{bucket}/files/{file_id}/audio", "expires_in": EXPIRES}


def iso(now):
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_version_id(now, rand):
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{rand}"


def gpu_request(file_uri, body):
    """Body of POST /transcribe -> (GPU request body, settings to store)."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    codes, diarize = body.get("language_codes", []), body.get("diarization", False)
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise ValueError("language_codes must be a list of strings")
    if not isinstance(diarize, bool):
        raise ValueError("diarization must be true or false")
    _text(body.get("label", ""), "label", False)
    mode = {"type": "verbatim", "timestamp_granularities": ["word"]}
    if diarize:
        mode["diarization_mode"] = "speaker"
    tc = {"mode": mode}
    if codes:
        tc["language_codes"] = codes
    return ({"input": [{"type": "file", "file_uri": file_uri}], "generation_config": {"transcription_config": tc}},
            {"language_codes": codes, "diarization": diarize})


def summary(version):
    resp = version.get("response") or {}
    try:
        notes = resp["steps"][0]["content"][0].get("annotations", [])
    except (KeyError, IndexError, TypeError):
        notes = []
    out = {k: v for k, v in version.items() if k != "response"}
    out["text_chars"] = len(resp.get("output_text") or "")
    out["speakers"] = len({n["speaker"] for n in notes if n.get("speaker")})
    return out


def list_files(objects):
    """GCS list items under files/ -> file rows. Reads no object bodies: name and type are in the meta metadata."""
    files = {}
    for o in objects:
        parts = o["name"].split("/")
        if len(parts) < 3 or not ID_RE.match(parts[1]):
            continue
        f = files.setdefault(parts[1], {"versions": []})
        if parts[2] == "meta.json":
            f["meta"] = o.get("metadata") or {}
        elif parts[2] == "audio" and len(parts) == 3:
            f["size"] = int(o.get("size", 0))
        elif parts[2] == "versions" and len(parts) == 4 and parts[3].endswith(".json"):
            f["versions"].append(parts[3][:-5])
    rows = [{"id": fid, "name": f["meta"].get("name", ""), "mime_type": f["meta"].get("mime_type", ""),
             "size_bytes": f["size"], "created": f["meta"].get("created", ""), "versions": len(f["versions"]),
             "latest": max(f["versions"], default=None)}
            for fid, f in files.items() if "meta" in f and "size" in f]
    return sorted(rows, key=lambda r: r["created"], reverse=True)


def _json(data):
    try:
        return json.loads(data)
    except ValueError:
        return None


def route(method, path, body, store, gpu, cfg, now):
    """All route logic. Returns (HTTP status, JSON answer). Ids are checked before any store call."""
    parts = path.split("?")[0].strip("/").split("/")
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
    if parts[:2] != ["v1beta", "files"]:
        return 404, error("not found", 404)
    rest = parts[2:]
    if method == "GET" and not rest:
        return 200, {"files": list_files(store.list("files/"))}
    shape = (method, len(rest), rest[1] if len(rest) > 1 else None)
    if shape not in {("GET", 1, None), ("POST", 2, "transcribe"), ("GET", 3, "versions")}:
        return 404, error("not found", 404)
    fid = rest[0]
    if not ID_RE.match(fid) or (len(rest) == 3 and not VERSION_RE.match(rest[2])):
        return 400, error("bad file id or version id")
    base = f"files/{fid}/"
    if not any(o["name"] == base + "audio" for o in store.list(base + "audio")):  # as GET /v1beta/files: no audio, no file
        return 404, error("file not found (no audio)", 404)
    if len(rest) == 1:
        try:
            meta = json.loads(store.read(base + "meta.json"))
        except KeyError:
            return 404, error("file not found", 404)
        vs = [summary(json.loads(store.read(o["name"]))) for o in store.list(base + "versions/")]
        return 200, {"file": meta, "versions": sorted(vs, key=lambda v: v["id"], reverse=True)}
    if len(rest) == 3:
        try:
            return 200, json.loads(store.read(f"{base}versions/{rest[2]}.json"))
        except KeyError:
            return 404, error("version not found", 404)
    try:
        req, settings = gpu_request(f"gs://{cfg['bucket']}/{base}audio", body)
    except ValueError as e:
        return 400, error(str(e))
    t, t0 = now(), time.monotonic()
    status, data = gpu(cfg["target"], req)
    if status != 200:
        return status, _json(data) or error(data.decode(errors="replace")[:500], status)
    answer_json = _json(data)
    if not isinstance(answer_json, dict):  # a saved version is never deleted, so it must be readable later
        return 502, error("the GPU answer is not a JSON object", 502)
    version = {"id": new_version_id(t, secrets.token_hex(2)), "file_id": fid, "created": iso(t),
               "label": body.get("label", ""), "image_tag": cfg["image_tag"], "settings": settings,
               "run_seconds": round(time.monotonic() - t0, 1), "response": answer_json}
    store.write(f"{base}versions/{version['id']}.json", json.dumps(version).encode(), "application/json")
    return 201, version


def token():
    if time.time() > _tok["exp"] - 60:
        r = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
        d = json.load(urllib.request.urlopen(r, timeout=5))
        _tok.update(value=d["access_token"], exp=time.time() + d["expires_in"])
    return _tok["value"]


def _auth(extra=None):
    return {"Authorization": f"Bearer {token()}", **(extra or {})}


class GcsStore:
    """GCS JSON API. write never replaces an object (ifGenerationMatch=0)."""

    def __init__(self, bucket):
        self.api = f"https://{HOST}/storage/v1/b/{bucket}/o"
        self.upload = f"https://{HOST}/upload/storage/v1/b/{bucket}/o"

    def list(self, prefix):
        items, page = [], None
        while True:
            q = {"prefix": prefix, **({"pageToken": page} if page else {})}
            d = json.load(urllib.request.urlopen(urllib.request.Request(f"{self.api}?{urlencode(q)}", headers=_auth()),
                                                 timeout=30))
            items += d.get("items", [])
            page = d.get("nextPageToken")
            if not page:
                return items

    def read(self, name):
        try:
            r = urllib.request.Request(f"{self.api}/{quote(name, safe='')}?alt=media", headers=_auth())
            return urllib.request.urlopen(r, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise KeyError(name) from e
            raise

    def write(self, name, data, content_type, metadata=None):
        b = "stt-files-boundary"
        head = json.dumps({"name": name, "contentType": content_type, "metadata": metadata or {}})
        body = (f"--{b}\r\nContent-Type: application/json\r\n\r\n{head}\r\n--{b}\r\n"
                f"Content-Type: {content_type}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        r = urllib.request.Request(f"{self.upload}?uploadType=multipart&ifGenerationMatch=0", body,
                                   _auth({"Content-Type": f"multipart/related; boundary={b}"}))
        urllib.request.urlopen(r, timeout=30).read()


def gpu_post(target, body):
    r = urllib.request.Request(target, json.dumps(body).encode(), _auth({"Content-Type": "application/json"}))
    try:
        with urllib.request.urlopen(r, timeout=GPU_TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def sign_blob(sa_email):
    url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{sa_email}:signBlob"

    def sign(data):
        body = json.dumps({"payload": base64.b64encode(data).decode()}).encode()
        r = urllib.request.Request(url, body, _auth({"Content-Type": "application/json"}))
        return base64.b64decode(json.load(urllib.request.urlopen(r, timeout=10))["signedBlob"])

    return sign


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    store = cfg = None  # set in __main__

    def reply(self, code, obj=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        for k, v in CORS.items():
            self.send_header(k, v)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.reply(204)

    def handle_call(self, method):
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size < 0:  # read(-1) waits for the end of the stream
                raise ValueError("negative Content-Length")
            raw = self.rfile.read(size)
            body = json.loads(raw) if raw else None
        except ValueError as e:  # bad Content-Length or bad JSON
            return self.reply(400, error(f"bad request body: {e}"))
        try:
            code, obj = route(method, self.path, body, self.store, gpu_post, self.cfg,
                              lambda: datetime.now(timezone.utc))
        except Exception:  # the gateway must always get an answer with CORS headers; details go to the log only
            traceback.print_exc()
            code, obj = 500, error("internal error", 500)
        self.reply(code, obj)

    def do_GET(self):
        self.handle_call("GET")

    def do_POST(self):
        self.handle_call("POST")


if __name__ == "__main__":
    H.store = GcsStore(os.environ["AUDIO_BUCKET"])
    H.cfg = {"bucket": os.environ["AUDIO_BUCKET"], "sa_email": os.environ["SA_EMAIL"],
             "image_tag": os.environ.get("IMAGE_TAG", ""), "target": os.environ["TARGET"],
             "sign": sign_blob(os.environ["SA_EMAIL"])}
    ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
