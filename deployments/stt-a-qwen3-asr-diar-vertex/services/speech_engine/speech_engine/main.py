"""STT-A GPU service: the HTTP server. Qwen3-ASR + Qwen3-ForcedAligner + Pyannote behind the Gemini 3.5 Transcribe
contract, in a Vertex AI custom container. The transcription work is in pipeline.py.

Routes (through :rawPredict, predict_route):
  GET  /health                503 while the 3 models load, then 200
  POST /v1beta/interactions   Gemini Interactions body -> output_text + word_info annotations

Run with 1 process only: each process loads all 3 models. Spec: docs/specs/2026-11-21-stt-a-design.md.
"""
from __future__ import annotations

import asyncio
import os
import traceback
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from speech_engine.logic import BadRequest, error_body, parse_request
from speech_engine.pipeline import Models, transcribe

try:  # registers Qwen3-ASR in the vLLM model registry, also in a vLLM engine process made with spawn
    import qwen_asr  # noqa: F401
except ImportError:  # unit tests run without the model packages
    pass

# What made the answer (main.tf sets the values). The STT API service saves it with each version, to compare setups.
SETUP = {k: os.environ.get(f"SETUP_{k.upper()}", "") for k in ("asr", "aligner", "diarization", "image_tag")}


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
                return {**await asyncio.to_thread(transcribe, m, job), "setup": SETUP}
        except BadRequest as e:
            return JSONResponse(error_body(str(e)), status_code=400)
        except Exception:  # noqa: BLE001 - the details go to the log only, not to the caller
            traceback.print_exc()
            return JSONResponse(error_body("internal error", 500), status_code=500)

    return app


if __name__ == "__main__":
    import uvicorn

    from speech_engine.models import RealModels

    uvicorn.run(create_app(RealModels, os.environ["AUDIO_BUCKET"]), host="0.0.0.0",
                port=int(os.environ.get("AIP_HTTP_PORT", "8080")), workers=1)
