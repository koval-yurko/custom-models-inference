"""LLM-B: own FastAPI app with the vLLM engine (AsyncLLM) in the same process. Vertex AI custom container.

Routes (through :invoke, <base>/invoke/<route>):
  GET  /health    200 when the engine is ready, 503 while it loads or after it failed
  POST /generate  {"prompt", "max_tokens"?, "temperature"?} -> {"text"}
  POST /extract   {"text", "schema"?, "max_tokens"?} -> {"data"}: JSON that matches the schema (structured outputs)

API checked against vllm 0.33.0 (the base image tag in the Dockerfile). Run with 1 process only: each process loads the model.
"""
import asyncio
import json
import os
import traceback
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from vllm import AsyncEngineArgs, SamplingParams
from vllm.sampling_params import StructuredOutputsParams
from vllm.v1.engine.async_llm import AsyncLLM  # what vllm.AsyncLLMEngine points to in vLLM v1

# Vertex AI sets AIP_STORAGE_URI (gs://...) from the model artifactUri. MODEL is for a local run with a local folder.
MODEL = os.environ.get("AIP_STORAGE_URI") or os.environ["MODEL"]

ENGINE_ARGS = AsyncEngineArgs(
    model=MODEL,
    served_model_name=[os.environ.get("SERVED_MODEL_NAME", "qwen3.5-9b")],
    # Streams the safetensors from GCS to the GPU. A local folder loads as usual.
    load_format="runai_streamer" if MODEL.startswith("gs://") else "auto",
    max_model_len=int(os.environ.get("MAX_MODEL_LEN", "16384")),
    kv_cache_dtype="fp8",
    # Qwen3.5 is an image-text model. Text only: no vision encoder on the GPU, more room for the KV cache.
    language_model_only=True,
)

DEFAULT_SCHEMA = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "organizations": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "string"}},
        "dates": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["people", "organizations", "places", "dates"],
    "additionalProperties": False,
}

engine: AsyncLLM | None = None


async def load_engine():
    """Load in a thread, so uvicorn opens the port at once (Vertex AI liveness is a TCP probe) and /health says 503."""
    global engine
    try:
        engine = await asyncio.to_thread(AsyncLLM.from_engine_args, ENGINE_ARGS)
        print("engine ready", flush=True)  # scale-alerts reads this line: uvicorn starts before the model loads
    except BaseException:  # noqa: BLE001 - exit, so the error is in the log and the container restarts
        traceback.print_exc()
        os._exit(1)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(load_engine())
    yield
    task.cancel()
    if engine:
        engine.shutdown()


app = FastAPI(title="llm-b-qwen35-9b-fastapi", lifespan=lifespan)


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(512, ge=1, le=4096)
    temperature: float = Field(0.7, ge=0.0, le=2.0)


class ExtractIn(BaseModel):
    text: str = Field(min_length=1)
    schema_: dict | None = Field(None, alias="schema", description="JSON schema of the answer. Default: people, organizations, places, dates.")
    max_tokens: int = Field(1024, ge=1, le=4096)


def ready() -> AsyncLLM:
    if engine is None:
        raise HTTPException(503, "model is loading")
    return engine


async def complete(messages: list[dict], params: SamplingParams) -> str:
    eng = ready()
    # Qwen3.5 thinks by default. The routes want the answer only.
    prompt = eng.get_tokenizer().apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    final = None
    try:
        async for out in eng.generate(prompt, params, str(uuid.uuid4())):
            final = out
    except ValueError as e:  # for example a prompt longer than MAX_MODEL_LEN
        raise HTTPException(400, str(e)) from e
    return final.outputs[0].text


@app.get("/health")
async def health():
    if engine is None:
        return JSONResponse({"status": "loading"}, status_code=503)
    try:
        await engine.check_health()
    except Exception as e:  # noqa: BLE001 - engine core is dead: 503 makes Vertex AI replace the replica
        return JSONResponse({"status": "error", "detail": repr(e)}, status_code=503)
    return {"status": "ok"}


@app.post("/generate")
async def generate(body: GenerateIn):
    params = SamplingParams(max_tokens=body.max_tokens, temperature=body.temperature)
    return {"text": await complete([{"role": "user", "content": body.prompt}], params)}


@app.post("/extract")
async def extract(body: ExtractIn):
    schema = body.schema_ or DEFAULT_SCHEMA
    params = SamplingParams(max_tokens=body.max_tokens, temperature=0.0,
                            structured_outputs=StructuredOutputsParams(json=schema))
    messages = [
        {"role": "system", "content": "Extract the data from the text. Answer with JSON that matches this schema:\n"
                                      + json.dumps(schema)},
        {"role": "user", "content": body.text},
    ]
    text = await complete(messages, params)
    try:
        return {"data": json.loads(text)}
    except json.JSONDecodeError as e:  # only when max_tokens cuts the JSON
        raise HTTPException(502, f"model output is not complete JSON (raise max_tokens): {e}") from e


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("AIP_HTTP_PORT", "8080")), workers=1)
