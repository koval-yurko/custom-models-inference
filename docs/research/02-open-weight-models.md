# Research: Open-weight models to deploy

Date: 2026-11-08. Card: "Project setup". Platform: Cloud Run GPU (see `01-serverless-inference-on-gcp.md`).

## Goal

Deploy 2 LLM services:

| ID | Deployment type | Image |
|---|---|---|
| A | Regular vLLM (OpenAI-compatible server, flags only) | `vllm/vllm-openai` |
| B | Own FastAPI app that calls vLLM `AsyncLLMEngine` in the same process | custom image `FROM vllm/vllm-openai` |

Also make a short list of STT and TTS models for later cards.

## Constraints

- 1 GPU per Cloud Run instance: L4 (24 GB) or RTX PRO 6000 (96 GB).
- L4 (Ada) supports FP8. Native FP4 (NVFP4, MXFP4) tensor cores need Blackwell (RTX PRO 6000).
- VRAM must hold the weights plus the KV cache. On L4, plan weights of at most about 16 GB.
- Small weights give a faster cold start (scale to zero).
- Licenses: prefer Apache 2.0 or MIT. Avoid licenses with usage caps.

Memory rule: BF16 is about 2 GB per 1B parameters. FP8 is about 1 GB. 4-bit is about 0.5 GB to 0.6 GB.

## Candidate LLMs (November 2026)

| Model | Type | Params (total / active) | License | Fits L4 24 GB | Fits RTX PRO 6000 96 GB | Notes |
|---|---|---|---|---|---|---|
| Qwen3.5-9B | Dense | 9B | Apache 2.0 | Yes (FP8 about 10 GB, BF16 about 18 GB with small context) | Yes | Released March 2026. Small, fast cold start. |
| Gemma 4 26B A4B (QAT w4a16) | MoE | 25.2B / 3.8B | Apache 2.0 (from Gemma 4) | Yes (about 13 GB) | Yes (BF16 about 52 GB) | Google shows it on Cloud Run L4 with vLLM. Fast, because only 3.8B params are active. Image input. |
| gpt-oss-20b | MoE | 21B / 3.6B | Apache 2.0 | Probably (about 16 GB, MXFP4) | Yes | L4 is not on the official vLLM hardware list. Uses the Marlin fallback kernel. Test first. |
| Qwen3.6-35B-A3B | MoE | 35B / 3B | Apache 2.0 | Only 4-bit (about 20 GB), little room for KV cache | Yes (BF16 about 70 GB) | Released April 2026. |
| Mistral Small 3.2 24B | Dense | 24B | Apache 2.0 | 4-bit only (about 14 GB) | Yes | Good tool calls, image input. |
| Qwen3.8-27B (FP8) | Dense | 27B | Apache 2.0 | No (FP8 about 28 GB) | Yes, with large KV cache | Released August 2026. Strongest model in this list for 1 GPU. 262K context. Needs a recent vLLM (0.17 or later per third-party guides). |
| Gemma 4 31B | Dense | 30.7B | Apache 2.0 | No | Yes (FP8 about 31 GB) | 256K context. |

Not in scope: models that need more than 1 GPU (Qwen3.8-2.4T-A95B, Mistral Large 3, Llama 4 Maverick, gpt-oss-120b in BF16). Llama 4 also has a custom license with a usage cap.

## Recommendation

Status: A and B approved by the user on 2026-11-08. Each one gets its own folder: `deployments/llm-a-gemma4-12b-vllm/` and `deployments/llm-b-qwen35-9b-fastapi/` (see the Terraform layout in `01-serverless-inference-on-gcp.md`).

Use 2 different architectures and 2 vendors, both on L4. This keeps the cost at about $1 per hour for each running instance. Both scale to zero.

### A: Regular vLLM -> Gemma 4 26B A4B (QAT w4a16) on L4

Update 2026-11-09: Google publishes no QAT w4a16 checkpoint for 26B A4B. The `-qat-w4a16-ct` format exists only for E2B, E4B, 12B and 31B. The user chose `google/gemma-4-12B-it-qat-w4a16-ct` (dense 12B, 10.3 GB) instead. The deployment is `deployments/llm-a-gemma4-12b-vllm/`. The text below is the original plan.

1. It is a MoE model. Only 3.8B parameters are active, so tokens come fast on an L4.
2. Google uses this setup on Cloud Run L4 in its own examples, so the risk is low.
3. The weights are about 13 GB, so the cold start is short and there is room for the KV cache.
4. No custom code is necessary. Terraform `args` are enough:

```
--model /models/gemma-4-26b-a4b-it-qat-w4a16
--served-model-name gemma-4-26b-a4b
--max-model-len 32768
--kv-cache-dtype fp8
--host 0.0.0.0 --port 8080
```

Risk: one hosting provider says the 4-bit quality for this MoE model is low. Compare the answers with the hosted Gemma API in the first test. If the quality is not good, use `gpt-oss-20b` or `Qwen3.5-9B` on the same service.

### B: FastAPI + AsyncLLMEngine -> Qwen3.5-9B (FP8) on L4

1. It is a dense model from a different vendor, so it gives a second architecture to compare.
2. The FP8 weights are about 10 GB. Cold start is short, so you can test custom code quickly.
3. Qwen models are good at tool calls and JSON output. These are typical tasks for custom Python code.
4. Upgrade path: change the model to Qwen3.8-27B FP8 and the GPU to RTX PRO 6000. The code does not change.

Example custom logic for B (select 1 or 2 for the first version):

- An own route, for example `/summarize` or `/extract`, with a fixed prompt and a JSON schema (guided decoding).
- Pre-processing (PII mask) and post-processing (validation, retries) around the model call.
- Several model calls in one request (draft, then check).
- Own auth, logs and metrics per request.

Skeleton:

```python
# app.py - check the API against the vLLM version in the image
import uuid
from fastapi import FastAPI
from vllm import AsyncEngineArgs, AsyncLLMEngine, SamplingParams

engine = AsyncLLMEngine.from_engine_args(AsyncEngineArgs(
    model="/models/qwen3.5-9b-fp8",
    max_model_len=16384,
))
app = FastAPI()

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/generate")
async def generate(body: dict):
    params = SamplingParams(max_tokens=body.get("max_tokens", 512), temperature=0.7)
    final = None
    async for out in engine.generate(body["prompt"], params, str(uuid.uuid4())):
        final = out
    return {"text": final.outputs[0].text}
```

Run it with `uvicorn app:app --host 0.0.0.0 --port 8080` and only 1 worker. Each worker loads the model again.

## STT and TTS

See `03-speech-models.md` for the full review.

## What to check before deployment

1. Open each Hugging Face model card. Confirm the exact repo name, license and the vLLM version.
2. Use the latest stable `vllm/vllm-openai` tag. Qwen3.8 and Gemma 4 need recent versions.
3. Copy the weights into the Cloud Storage bucket one time. Do not download from Hugging Face on each cold start.
4. Measure the cold start and tokens per second for A and B. Write the results in a new doc.

## Sources

- [Qwen3.8-27B-FP8 model card](https://huggingface.co/Qwen/Qwen3.8-27B-FP8)
- [Qwen3.8 GitHub](https://github.com/QwenLM/Qwen3.8)
- [Qwen3.8-27B vLLM guide (third party)](https://www.orcarouter.ai/blog/qwen-3-8-27b-vllm)
- [Gemma 4 26B on Cloud Run L4 (GDE)](https://dev.to/gde/26b-gemma-4-deployment-with-nvidia-l4-mcp-cloud-run-and-antigravity-cli-194p)
- [Gemma 4 26B on GKE with 1 L4](https://dev.to/ratibor78/running-gemma-4-26b-on-gke-with-a-single-l4-gpu-4l6g)
- [Gemma 4 with vLLM: 4-bit formats](https://wz-it.com/en/knowledge/ki/gemma-4-vllm-w4a16-vs-gguf/)
- [Gemma (Wikipedia)](https://en.wikipedia.org/wiki/Gemma_(language_model))
- [vLLM recipe: gpt-oss-20b](https://recipes.vllm.ai/openai/gpt-oss-20b)
- [OpenAI cookbook: gpt-oss with vLLM](https://developers.openai.com/cookbook/articles/gpt-oss/run-vllm)
- [Best open-source LLMs, October 2026 (third party)](https://www.morphllm.com/best-open-source-llm)
- [Open-weight models 2026 (third party)](https://slash-digital.io/en/insights/open-weight-models-2026/)
- [Best local LLM by VRAM (third party)](https://vdf.ai/blog/best-local-llm-by-vram/)
- [Qwen 3.8 lineup (third party)](https://codersera.com/blog/qwen-3-8-model-lineup-2026)
- [Open-source STT models 2026](https://pinggy.io/blog/best_open_source_self_hosted_speech_to_text_models/)
- [Open-source TTS models 2026](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/)
