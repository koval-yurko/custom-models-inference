"""Rules of the STT-A service (spec: docs/specs/2026-11-21-stt-a-design.md). Standard library only."""
from __future__ import annotations

import base64
import binascii
import math
import uuid
from dataclasses import dataclass

LANGS: dict[str, str] = {
    "zh": "Chinese", "en": "English", "yue": "Cantonese", "ar": "Arabic", "de": "German", "fr": "French",
    "es": "Spanish", "pt": "Portuguese", "id": "Indonesian", "it": "Italian", "ko": "Korean", "ru": "Russian",
    "th": "Thai", "vi": "Vietnamese", "ja": "Japanese", "tr": "Turkish", "hi": "Hindi", "ms": "Malay",
    "nl": "Dutch", "sv": "Swedish", "da": "Danish", "fi": "Finnish", "pl": "Polish", "cs": "Czech",
    "fil": "Filipino", "tl": "Filipino", "fa": "Persian", "el": "Greek", "hu": "Hungarian", "mk": "Macedonian",
    "ro": "Romanian", "zh-hk": "Cantonese", "zh-yue": "Cantonese",
}
ALIGNER_LANGS = frozenset({"Chinese", "English", "Cantonese", "French", "German", "Italian", "Japanese",
                           "Korean", "Portuguese", "Russian", "Spanish"})

MERGE_GAP = 1.0
MIN_TURN = 0.2
MAX_TURN = 180.0  # aligner limit of qwen-asr (MAX_FORCE_ALIGN_INPUT_SECONDS)
MODEL = "qwen3-asr-diar"


class BadRequest(Exception):
    pass


@dataclass
class Job:
    data: bytes | None
    gcs_uri: str | None
    language: str | None
    diarize: bool
    words: bool


@dataclass
class Turn:
    start: float
    end: float
    speaker: str | None


@dataclass
class Word:
    text: str
    start: float
    end: float


def _language(codes) -> str | None:
    if codes is not None and not isinstance(codes, list):
        raise BadRequest("language_codes must be a list")
    if not codes or len(codes) != 1:
        return None
    code = str(codes[0]).lower()
    name = LANGS.get(code) or LANGS.get(code.split("-")[0])
    if not name:
        raise BadRequest(f"unsupported language code: {codes[0]}")
    return name


def _audio(item: dict, audio_bucket: str, max_bytes: int) -> tuple[bytes | None, str | None]:
    if not isinstance(item, dict):
        raise BadRequest("input item must be an object")
    if item.get("data") is not None:
        try:
            data = base64.b64decode(item["data"], validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise BadRequest("input data is not valid base64")
        if not data:
            raise BadRequest("input data is empty")
        if len(data) > max_bytes:
            raise BadRequest(f"inline audio is larger than {max_bytes} bytes; use /v1beta/uploads")
        return data, None
    uri = item.get("uri") or item.get("file_uri")
    if not isinstance(uri, str) or not uri:
        raise BadRequest("input item has no data, uri or file_uri")
    if not uri.startswith("gs://"):
        raise BadRequest("only gs:// URIs are supported")
    if not uri.startswith(f"gs://{audio_bucket}/") or uri == f"gs://{audio_bucket}/":
        raise BadRequest(f"only objects in gs://{audio_bucket}/ are supported")
    return None, uri


def parse_request(body: dict, audio_bucket: str, max_bytes: int = 20_000_000) -> Job:
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    items = body.get("input")
    if not isinstance(items, list) or len(items) != 1:
        raise BadRequest("input must hold exactly 1 audio item")
    data, uri = _audio(items[0], audio_bucket, max_bytes)
    gc = body.get("generation_config") or {}
    if not isinstance(gc, dict):
        raise BadRequest("generation_config must be an object")
    tc = gc.get("transcription_config") or {}
    if not isinstance(tc, dict):
        raise BadRequest("transcription_config must be an object")
    if "custom_vocabulary" in tc:
        raise BadRequest("custom_vocabulary is not supported")
    mode = tc.get("mode", "verbatim")
    mode = {"type": mode} if isinstance(mode, str) else (mode or {})
    if not isinstance(mode, dict):
        raise BadRequest("mode must be a string or an object")
    kind = mode.get("type", "verbatim")
    if kind not in ("verbatim", "smart"):
        raise BadRequest(f"unknown mode: {kind}")
    grans = mode.get("timestamp_granularities") or []
    if not isinstance(grans, list):
        raise BadRequest("timestamp_granularities must be a list")
    if kind == "smart" and (mode.get("diarization_mode") or grans):
        raise BadRequest("smart mode does not support diarization_mode or timestamp_granularities; use verbatim")
    return Job(data=data, gcs_uri=uri, language=_language(tc.get("language_codes")),
               diarize=mode.get("diarization_mode") == "speaker", words="word" in grans)


def check_duration(seconds: float, limit: float = 1800.0) -> None:
    if seconds > limit:
        raise BadRequest(f"audio is longer than {limit:.0f} s")


def _split(turn: Turn) -> list[Turn]:
    n = math.ceil((turn.end - turn.start) / MAX_TURN)
    step = (turn.end - turn.start) / n
    return [Turn(round(turn.start + i * step, 3), round(turn.start + (i + 1) * step, 3) if i < n - 1 else turn.end,
                 turn.speaker) for i in range(n)]


def make_turns(segments: list[tuple[float, float, str]], total: float, diarize: bool) -> list[Turn]:
    if not diarize:
        return _split(Turn(0, total, None)) if total > 0 else []
    merged: list[Turn] = []
    for start, end, spk in sorted(segments):
        if end - start < MIN_TURN:
            continue
        last = merged[-1] if merged else None
        if last and last.speaker == spk and start - last.end <= MERGE_GAP:
            last.end = max(last.end, end)
        else:
            merged.append(Turn(start, end, spk))
    return [t for turn in merged for t in _split(turn)]


def longest_clip(turns: list[Turn], max_len: float = 30.0) -> tuple[float, float]:
    t = max(turns, key=lambda t: t.end - t.start)
    return t.start, min(t.end, t.start + max_len)


def estimate_words(text: str, start: float, end: float) -> list[Word]:
    parts = text.split()
    total = sum(len(p) for p in parts)
    words, pos = [], start
    for p in parts:
        nxt = pos + (end - start) * len(p) / total
        words.append(Word(p, round(pos, 3), round(nxt, 3)))
        pos = nxt
    return words


def label_speakers(turns: list[Turn]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for t in sorted(turns, key=lambda t: t.start):
        if t.speaker is not None and t.speaker not in labels:
            labels[t.speaker] = f"spk_{len(labels) + 1}"
    return labels


def fmt_offset(seconds: float) -> str:
    return f"{seconds:.3f}s"


def build_response(turns: list[Turn], texts: list[str], words: list[list[Word]], labels: dict[str, str],
                   job: Job) -> dict:
    text = "\n".join(t for t in texts if t)
    content: dict = {"type": "text", "text": text}
    if job.diarize or job.words:
        notes = []
        for turn, ws in zip(turns, words):
            for w in ws:
                note = {"type": "word_info", "text": w.text}
                if job.diarize and turn.speaker is not None:
                    note["speaker"] = labels[turn.speaker]
                note["start_offset"] = fmt_offset(w.start)
                note["end_offset"] = fmt_offset(w.end)
                notes.append(note)
        if notes:
            content["annotations"] = notes
    return {"id": str(uuid.uuid4()), "status": "completed", "model": MODEL, "output_text": text,
            "steps": [{"type": "model_output", "content": [content]}]}


def error_body(message: str, code: int = 400) -> dict:
    status = {400: "INVALID_ARGUMENT", 503: "UNAVAILABLE"}.get(code, "INTERNAL")
    return {"error": {"code": code, "message": message, "status": status}}
