"""STT-A GPU service: the HTTP server. Qwen3-ASR + Qwen3-ForcedAligner + Pyannote behind the Gemini 3.5 Transcribe
contract, in a Vertex AI custom container or a Runpod worker (the same image). The transcription work is in pipeline.py.

Routes (Vertex AI: through :rawPredict, predict_route; Runpod: the load balancing endpoint):
  GET  /health                while the 3 models load: 503 (Vertex AI) or 204 (Runpod), then 200
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
from fastapi.responses import JSONResponse, Response

from speech_engine.logic import BadRequest, error_body, parse_request
from speech_engine.pipeline import Models, transcribe

try:  # registers Qwen3-ASR in the vLLM model registry, also in a vLLM engine process made with spawn
    import qwen_asr  # noqa: F401
except ImportError:  # unit tests run without the model packages
    pass

# What made the answer (main.tf and the platform adapter set the values). The STT API service saves it with each
# version, to compare setups. The answer adds "gpu" (the GPU name of the loaded models).
SETUP = {k: os.environ.get(f"SETUP_{k.upper()}", "") for k in ("asr", "aligner", "diarization", "image_tag", "platform")}


def port(environ) -> int:
    """PORT (container contract, the Runpod adapter sets it), else AIP_HTTP_PORT (Vertex AI), else 8080."""
    return int(environ.get("PORT") or environ.get("AIP_HTTP_PORT") or "8080")


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
    async def health(request: Request):
        # Runpod load balancing reads 204 as "initializing" and any other code as unhealthy: it stopped the worker
        # after about 10 min of 503 (worker log 2026-11-24 "container is unhealthy: dead"), before the load ended.
        code = 200 if state["models"] is not None else 204 if SETUP["platform"] == "runpod" else 503
        if code != state.get("health"):  # 1 line per change: shows that the platform probe arrives, and from where
            state["health"] = code
            print(f"health {code} to {request.client.host if request.client else '-'}", flush=True)
        if code == 204:
            return Response(status_code=204)
        if code == 503:
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
                return {**await asyncio.to_thread(transcribe, m, job),
                        "setup": {**SETUP, "gpu": getattr(m, "gpu", "")}}
        except BadRequest as e:
            return JSONResponse(error_body(str(e)), status_code=400)
        except Exception:  # noqa: BLE001 - the details go to the log only, not to the caller
            traceback.print_exc()
            return JSONResponse(error_body("internal error", 500), status_code=500)

    return app


if __name__ == "__main__":
    import uvicorn

    from speech_engine.models import RealModels

    # Runpod: "::" takes IPv6 and IPv4 on Linux, in case the load balancer probe comes over IPv6.
    uvicorn.run(create_app(RealModels, os.environ["AUDIO_BUCKET"]), host="::" if SETUP["platform"] == "runpod" else "0.0.0.0",
                port=port(os.environ), workers=1)
