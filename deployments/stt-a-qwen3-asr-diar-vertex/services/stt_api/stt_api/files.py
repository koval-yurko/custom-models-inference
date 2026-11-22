"""Uploads and transcript history: request checks, the file list, version summaries and speaker names.
Pure functions; routes.py calls them, gcp.py does the I/O."""
import re

from stt_api.bucket import ID_RE, NAMES, REFERENCE
from stt_api.gcp import EXPIRES

AUDIO_TYPES = frozenset({"audio/wav", "audio/mp3", "audio/aiff", "audio/aac", "audio/ogg", "audio/flac", "audio/mpeg",
                         "audio/m4a", "audio/l16", "audio/opus", "audio/alaw", "audio/mulaw", "audio/webm"})
MAX_BYTES = 500_000_000
MAX_TEXT = 200
MAX_NAMES, MAX_NAME = 8, 40
SPEAKER_RE = re.compile(r"^spk_\d{1,2}$")


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
        elif parts[2] == REFERENCE and len(parts) == 3:
            f["reference"] = True
        elif parts[2] == "versions" and len(parts) == 4 and parts[3].endswith(".json") and not parts[3].endswith(NAMES):
            f["versions"].append(parts[3][:-5])
    rows = [{"id": fid, "name": f["meta"].get("name", ""), "mime_type": f["meta"].get("mime_type", ""),
             "size_bytes": f["size"], "created": f["meta"].get("created", ""), "versions": len(f["versions"]),
             "latest": max(f["versions"], default=None), "reference": f.get("reference", False)}
            for fid, f in files.items() if "meta" in f and "size" in f]
    return sorted(rows, key=lambda r: r["created"], reverse=True)


def check_names(body):
    """{"spk_1": "Alice"}: at most 8 speaker labels, each name 1 to 40 chars after strip. {} removes all names."""
    if not isinstance(body, dict) or len(body) > MAX_NAMES:
        raise ValueError(f"body must be a JSON object with at most {MAX_NAMES} keys")
    out = {}
    for k, v in body.items():
        if not SPEAKER_RE.match(k):
            raise ValueError(f"bad speaker label {k!r}: use spk_<n>")
        if not isinstance(v, str) or not 1 <= len(v.strip()) <= MAX_NAME:
            raise ValueError(f"name of {k} must be a string of 1 to {MAX_NAME} chars")
        out[k] = v.strip()
    return out
