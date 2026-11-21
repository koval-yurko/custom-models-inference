"""STT-A: Qwen3-ASR + Qwen3-ForcedAligner + Pyannote behind the Gemini 3.5 Transcribe contract. Vertex AI custom container.

Routes (through :rawPredict, predict_route):
  GET  /health                503 while the 3 models load, then 200
  POST /v1beta/interactions   Gemini Interactions body -> output_text + word_info annotations

Run with 1 process only: each process loads all 3 models. Spec: docs/specs/2026-11-21-stt-a-design.md.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import traceback
from contextlib import asynccontextmanager
from typing import Callable, Protocol

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.logic import (
    ALIGNER_LANGS, LANGS, BadRequest, Job, Turn, Word, build_response, check_duration, error_body,
    estimate_words, label_speakers, longest_clip, make_turns, parse_request,
)

try:  # registers Qwen3-ASR in the vLLM model registry, also in a vLLM engine process made with spawn
    import qwen_asr  # noqa: F401
except ImportError:  # unit tests run without the model packages
    pass

SR = 16000
NAMES = frozenset(LANGS.values())


class Models(Protocol):
    def diarize(self, audio: np.ndarray, sr: int) -> list[tuple[float, float, str]]: ...
    def transcribe(self, clips: list[np.ndarray], sr: int, language: str | None) -> list[tuple[str, str]]: ...
    def align(self, clip: np.ndarray, sr: int, text: str, language: str) -> list[Word]: ...
    def read_gcs(self, uri: str) -> bytes: ...


def decode(data: bytes) -> tuple[np.ndarray, int]:
    """Any ffmpeg format to 16 kHz mono float32. A file, not a pipe: m4a and mp4 need a seekable input."""
    with tempfile.NamedTemporaryFile() as f:
        f.write(data)
        f.flush()
        p = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", f.name,
                            "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise BadRequest(f"audio does not decode: {p.stderr.decode(errors='replace').strip()[:200]}")
    return np.frombuffer(p.stdout, np.float32), SR


def _cut(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    return audio[int(start * sr):int(end * sr)]


def _first_name(language: str) -> str | None:
    name = (language or "").split(",")[0].strip()
    return name if name in NAMES else None


def _word_times(m: Models, turn: Turn, clip: np.ndarray, sr: int, text: str, language: str | None) -> list[Word]:
    if not text:
        return []
    if language in ALIGNER_LANGS:
        try:
            aligned = m.align(clip, sr, text, language)
            if aligned:
                return [Word(w.text, round(w.start + turn.start, 3), round(w.end + turn.start, 3)) for w in aligned]
        except Exception:  # noqa: BLE001 - estimated times are better than HTTP 500
            traceback.print_exc()
    return estimate_words(text, turn.start, turn.end)


def transcribe(m: Models, job: Job) -> dict:
    audio, sr = decode(job.data if job.data is not None else m.read_gcs(job.gcs_uri))
    total = len(audio) / sr
    check_duration(total)
    turns = make_turns(m.diarize(audio, sr) if job.diarize else [], total, job.diarize)
    if not turns:
        return build_response([], [], [], {}, job)
    language = job.language
    if language is None:  # detect 1 time: short turns detect badly
        start, end = longest_clip(turns)
        language = _first_name(m.transcribe([_cut(audio, sr, start, end)], sr, None)[0][1])
    clips = [_cut(audio, sr, t.start, t.end) for t in turns]
    results = m.transcribe(clips, sr, language)
    texts = [text.strip() for text, _ in results]
    words = [_word_times(m, t, c, sr, text, language or _first_name(lang))
             for t, c, text, (_, lang) in zip(turns, clips, texts, results)]
    return build_response(turns, texts, words, label_speakers(turns), job)


def create_app(load: Callable[[], Models], audio_bucket: str) -> FastAPI:
    state: dict = {"models": None}
    lock = asyncio.Lock()  # 1 request at a time on the GPU

    async def boot():
        """Load in a thread, so uvicorn opens the port at once (Vertex AI liveness is a TCP probe)."""
        try:
            state["models"] = await asyncio.to_thread(load)
            print("models ready", flush=True)  # scale-alerts reads this line
        except Exception:  # noqa: BLE001 - exit, so the error is in the log and the container restarts. Not CancelledError: that is a normal shutdown
            traceback.print_exc()
            os._exit(1)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(boot())
        yield
        task.cancel()

    app = FastAPI(title="stt-a-qwen3-asr-diar", lifespan=lifespan)

    @app.get("/health")
    async def health():
        if state["models"] is None:
            return JSONResponse({"status": "loading"}, status_code=503)
        return {"status": "ok"}

    @app.post("/v1beta/interactions")
    async def interactions(request: Request):
        m = state["models"]
        if m is None:
            return JSONResponse(error_body("models are loading", 503), status_code=503)
        try:
            body = await request.json()
        except ValueError as e:
            return JSONResponse(error_body(f"body is not valid JSON: {e}"), status_code=400)
        try:
            job = parse_request(body, audio_bucket)
            async with lock:
                return await asyncio.to_thread(transcribe, m, job)
        except BadRequest as e:
            return JSONResponse(error_body(str(e)), status_code=400)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return JSONResponse(error_body(f"internal error: {e}", 500), status_code=500)

    return app


if __name__ == "__main__":
    import uvicorn

    from app.models import RealModels

    uvicorn.run(create_app(RealModels, os.environ["AUDIO_BUCKET"]), host="0.0.0.0",
                port=int(os.environ.get("AIP_HTTP_PORT", "8080")), workers=1)
