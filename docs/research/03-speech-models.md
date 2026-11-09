# Research: Open-weight STT and TTS models to deploy

Date: 2026-11-08. Card: "Project setup". Platform: Cloud Run (see `01-serverless-inference-on-gcp.md`).

## Goal

- Select STT (speech to text) and TTS (text to speech) models that run on Cloud Run with scale to zero.
- Use the same pattern as the LLMs: one folder per deployment under `deployments/`.
- Get at least one stock-image deployment and one custom-container deployment, as for LLM A and B.

## Constraints

- Speech models are small (0.08B to 4B). An L4 (24 GB) is enough for all of them. The RTX PRO 6000 is not necessary.
- Some TTS models run on CPU. Cloud Run without a GPU costs much less and starts faster.
- License: prefer Apache 2.0, MIT or CC-BY-4.0. Many good TTS models are non-commercial (NC). Avoid them, or mark them as "test only".
- An OpenAI-compatible API is a plus: `/v1/audio/transcriptions` for STT and `/v1/audio/speech` for TTS. Then one client works for all models.

## STT candidates

| Model | Size | License | Languages | Serving | Streaming | Notes |
|---|---|---|---|---|---|---|
| Qwen3-ASR-1.7B | 1.7B | Apache 2.0 | 30 + 22 Chinese dialects | vLLM (stock image) | Yes, through vLLM | Best open English average WER on the Open ASR Leaderboard (about 5.4%, Oct 2026). Same stack as the LLMs. |
| Whisper large-v3-turbo | 0.8B | MIT | 99 | faster-whisper + FastAPI (custom image) | Partly (chunks) | WER about 7.6%. Most languages, many tools. Good base for custom Python code (VAD, diarization). |
| Parakeet TDT 0.6B v3 | 0.6B | CC-BY-4.0 | 25 European | NVIDIA NeMo (custom image) | Yes | Fastest for batch. WER about 6.2%. Heavy NeMo image. |
| Canary-Qwen 2.5B | 2.5B | CC-BY-4.0 | English | NeMo | No | WER about 5.6%. English only. |
| Voxtral Mini 4B Realtime | 4B | Apache 2.0 | 13 | vLLM | Yes, real time | Good for live transcription. Larger. |

Not selected: Cohere Transcribe (gated access, no timestamps).

## TTS candidates

| Model | Size | License | Languages | Serving | Voice cloning | Notes |
|---|---|---|---|---|---|---|
| Kokoro-82M | 82M | Apache 2.0 | about 8 | Kokoro-FastAPI (`ghcr.io/remsky/kokoro-fastapi-gpu` or `-cpu`), OpenAI `/v1/audio/speech` | No (fixed voices) | Very small. Runs on CPU. High leaderboard score for its size. |
| Qwen3-TTS (0.6B, 1.7B) | 0.6B to 1.7B | Apache 2.0 | 10 | vLLM-Omni (`vllm serve <model> --omni`), OpenAI `/v1/audio/speech` | Yes (short clip, Base variant) | Streaming as 24 kHz PCM. Same vLLM family as the LLMs. |
| Chatterbox (Resemble AI) | about 0.5B | MIT | English (multilingual variant exists) | Own FastAPI (custom image) | Yes | Emotion control. Not checked: server and streaming support. |
| Orpheus 3B | 3B | Apache 2.0 (check: weights may be Llama-derived) | English + some | vLLM-based servers | Limited | Llama-based model. Check the license before use. |
| Dia | 1.6B | Apache 2.0 | English | Own FastAPI | Yes | Dialog with 2 speakers. |

Non-commercial or restricted, test only:

| Model | License | Reason |
|---|---|---|
| Voxtral 4B TTS | CC BY-NC 4.0 | Weights are non-commercial. Commercial use only through the Mistral API. |
| Fish Audio S2 Pro | Fish Audio Research License / NC | Commercial use needs a separate agreement. |
| XTTS-v2 | Coqui Public Model License | Non-commercial. |
| F5-TTS | CC-BY-NC (weights) | Non-commercial. |
| VibeVoice | Research license | Not for products. |

## Recommendation

Status: all 4 picks (STT-A, STT-B, TTS-A, TTS-B) approved by the user on 2026-11-08.

Deploy 4 speech services. Each one gets its own folder.

| ID | Folder | Model | Server | Hardware | Why |
|---|---|---|---|---|---|
| STT-A | `deployments/stt-a-qwen3-asr-vllm/` | Qwen3-ASR-1.7B | stock `vllm/vllm-openai` | L4 | Most accurate. Same image and module as LLM A. Only flags change. |
| STT-B | `deployments/stt-b-whisper-turbo-fastapi/` | Whisper large-v3-turbo | custom image: faster-whisper + FastAPI | L4 | Custom container example for speech. 99 languages. Room for custom code (VAD, word timestamps, diarization). |
| TTS-A | `deployments/tts-a-kokoro-cpu/` | Kokoro-82M | stock `ghcr.io/remsky/kokoro-fastapi-cpu` | CPU only (no GPU) | Cheapest. Fast cold start. Shows a deployment without a GPU. |
| TTS-B | `deployments/tts-b-qwen3-tts-vllm-omni/` | Qwen3-TTS-1.7B | vLLM-Omni image (`--omni`) | L4 | Voice cloning and streaming. Apache 2.0. |

Order of work:

1. TTS-A first. It needs no GPU quota, so it tests the Terraform module and Cloud Run at the lowest cost.
2. STT-A next. It reuses everything from LLM A.
3. STT-B and TTS-B after that. They need custom images or a second image type.

Notes per service:

- **STT-A:** Use the `vllm[audio]` extra if the stock image does not include it (see `01-serverless-inference-on-gcp.md`, Custom vLLM container). Then it becomes a level-2 custom image. Check this first.
- **STT-B:** Load the model one time at start. Use `compute_type="float16"` on L4. Use 1 Uvicorn worker.
- **TTS-A:** Cloud Run CPU service. Start with 4 vCPU and 8 GiB memory. Kokoro-82M is small, so it can live inside the image (no GCS volume).
- **TTS-B:** Check that vLLM-Omni has a release image for Cloud Run. If not, build `FROM vllm/vllm-openai` and install `vllm-omni` with a version that matches.
- **All:** Audio uploads go in the request body. Cloud Run allows up to 32 MiB for HTTP/1 requests. For longer audio, upload to Cloud Storage and send the path.

## What to check before deployment

1. Open each model card. Confirm the license, the exact repo name and the sample rate.
2. Confirm the vLLM version that supports Qwen3-ASR, and the vLLM-Omni version for Qwen3-TTS.
3. Confirm the Parakeet license (sources say CC-BY-4.0 or Apache 2.0). It is not in the first 4 services.
4. Measure the cold start, the real-time factor (STT) and the time to first audio (TTS).

## Sources

- [Open-source STT models 2026 (Pinggy)](https://pinggy.io/blog/best_open_source_self_hosted_speech_to_text_models/)
- [Open-source STT models 2026 (AssemblyAI)](https://www.assemblyai.com/blog/top-open-source-stt-options-for-voice-applications)
- [Open-source STT models 2026 (Gladia)](https://www.gladia.io/blog/best-open-source-speech-to-text-models)
- [Open-source STT benchmarks (Northflank)](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks)
- [STT leaderboard (Codesota)](https://www.codesota.com/speech/stt-leaderboard)
- [STT leaderboard (Artificial Analysis)](https://artificialanalysis.ai/speech-to-text/non-streaming)
- [Open-source STT models (Sevenlabs)](https://www.sevenlabs.site/blogs/best-open-source-speech-to-text-models-2026)
- [Open-source TTS models 2026 (Pinggy)](https://pinggy.io/blog/best_open_source_self_hosted_text_to_speech_models/)
- [Open-source TTS models by license (Cartesia)](https://www.cartesia.ai/learn/open-source-tts)
- [Open-source TTS models (BentoML)](https://www.bentoml.com/blog/exploring-the-world-of-open-source-text-to-speech-models)
- [Open-source TTS models (Speakeasy)](https://www.tryspeakeasy.io/blog/open-source-text-to-speech-2026)
- [Open-source TTS models (TextToLab)](https://texttolab.com/blog/open-source-text-to-speech)
- [vLLM-Omni Speech API](https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/speech_api/)
- [vLLM recipe: Qwen3-TTS](https://recipes.vllm.ai/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice)
- [Voxtral 4B TTS model card](https://huggingface.co/mistralai/Voxtral-4B-TTS-2603)
- [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
