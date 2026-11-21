# Research: Speaker diarization on top of Qwen3-ASR

Date: 2026-11-19. Card: "STT with Diarization". Status: research only. No decision is approved yet.

## Goal

- Add speaker diarization to the Qwen3-ASR-1.7B transcription (STT-A, see `03-speech-models.md`).
- Compare 4 options: Pyannote, WeSpeaker ResNet34, SpeechBrain, NVIDIA TitaNet-L.
- Give the service the same interface as Gemini 3.5 Transcribe: one transcribe call returns the text and a speaker for each word.

## Current state

- STT-A (card "4. STT-A: Qwen3-ASR-1.7B on stock vLLM on Vertex AI (L4)") is in Backlog. No STT service is deployed.
- Qwen3-ASR on stock vLLM returns text only. Search found no proof that the vLLM route `/v1/audio/transcriptions` returns word timestamps for Qwen3-ASR.
- Diarization gives speaker turns (start, end, speaker). To give a speaker to each word, the service also needs word timestamps.

## Word timestamps: Qwen3-ForcedAligner-0.6B

- Qwen released Qwen3-ForcedAligner-0.6B together with Qwen3-ASR. It takes audio plus a transcript and returns word timestamps.
- It supports 11 languages. Qwen3-ASR supports 30. Word timestamps, and so speakers per word, work only in those 11 languages.
- The `qwen-asr` Python package (with the `[vllm]` extra) runs Qwen3-ASR on vLLM and attaches the aligner (`--aligner-checkpoint Qwen/Qwen3-ForcedAligner-0.6B`).
- vLLM has a model class `qwen3_asr_forced_aligner`. Not checked: if stock `vllm serve` exposes it on an HTTP route.

## The 4 options

Important: the 4 names are not 4 equal choices. Pyannote is a full pipeline. WeSpeaker ResNet34 is the speaker embedding model inside the Pyannote pipeline. TitaNet-L is the embedding model inside the NVIDIA NeMo pipeline. SpeechBrain is a toolkit with the ECAPA-TDNN embedding model.

| Option | What it is | License | Full pipeline? | Fit for this repo |
|---|---|---|---|---|
| Pyannote `speaker-diarization-community-1` (pyannote.audio 4.x) | Segmentation + WeSpeaker ResNet34 embeddings + clustering | Code MIT, weights CC-BY-4.0. Hugging Face gate: accept the user conditions | Yes. Also returns `exclusive_speaker_diarization` (one speaker at a time), made for a join with ASR word timestamps | Best. One `pip install`, runs on the same L4, overlap and speaker count included |
| WeSpeaker ResNet34 | Speaker embedding model (wenet-e2e). Also has its own simple diarization recipe (VAD + embeddings + clustering) | Apache 2.0 (check the model card of the exact checkpoint) | Only the simple recipe. No overlap handling | Use it through Pyannote. Alone it gives less than Pyannote |
| SpeechBrain ECAPA-TDNN | Toolkit with an embedding model and example diarization recipes | Apache 2.0 (not checked) | Recipes only (AMI). No ready production pipeline | Weak. Much own code for clustering and overlap |
| NVIDIA TitaNet-L (NeMo) | Embedding model for the NeMo clustering diarizer (with MSDD). NVIDIA also ships Sortformer, an end-to-end diarizer | TitaNet-L: CC-BY-4.0 (not checked). Sortformer v2.1: NVIDIA Open Model License | Yes (NeMo clustering diarizer, or Sortformer) | Heavy NeMo image. Sortformer supports only 4 speakers |

Accuracy: no source compares the 4 options in one pipeline on the same data. Published DER figures use different data, collars and overlap rules, so they are not comparable. Pyannote states that community-1 is much better than 3.1 in speaker count and speaker assignment. Measure on our own audio before a final choice.

Speed: no official GPU real-time factor (RTF) for community-1 was found. One third-party CPU benchmark (Apple M2 Pro) gives RTF 0.82 for community-1 and 1.74 for 3.1. On an L4 it is expected to be much faster. Measure it.

## Target interface: Gemini 3.5 Transcribe

Source: the official page `https://aistudio.google.com/docs/transcribe` (was `ai.google.dev/gemini-api/docs/transcribe`). The model is in Preview.

Request (official REST example):

```json
POST /v1beta/interactions
{
  "model": "models/gemini-3.5-transcribe",
  "input": [{"type": "file", "file_uri": "YOUR_FILE_URI"}],
  "generation_config": {
    "transcription_config": {
      "language_codes": ["en-US"],
      "mode": {
        "type": "verbatim",
        "diarization_mode": "speaker",
        "timestamp_granularities": ["word"]
      }
    }
  }
}
```

Response:

- `output_text`: the full transcript.
- `steps[].content[].annotations[]` with `type == "word_info"`. Each word has `text`, `speaker` (`spk_1`, `spk_2`), `start_offset` and `end_offset` (for example `"0.100s"`).

Rules from the Gemini page:

- Diarization and word timestamps need `mode.type = "verbatim"`. The `"smart"` mode rejects them.
- `custom_vocabulary` cannot be used together with diarization or word timestamps.
- Up to 8 speakers. Google calls 3 or more speakers experimental.
- Up to 1 hour of audio, or 30 minutes with diarization or word timestamps.

Not checked: the full response JSON (the page shows no complete example), the offset type (string with `s` is from a summary of the page), and the inline audio form (`"type": "audio"` with `data` and `mime_type` is on the general audio page).

Proposal for our copy of the contract:

- Accept the same request body. Accept `file_uri` as a `gs://` path and inline base64 `data`.
- Return `output_text` and the `word_info` annotations with the same field names and the `spk_N` labels.
- Ignore `model`. Reject `"smart"` mode with diarization, as Gemini does.
- Add an optional `speaker_count` hint (Pyannote `num_speakers`). Gemini has no such field.

## Recommended shape

One custom container, "STT-C", on 1 L4:

1. FastAPI app. Load 3 models one time at start: Qwen3-ASR-1.7B (vLLM through `qwen-asr`), Qwen3-ForcedAligner-0.6B, Pyannote community-1. All 3 fit in 24 GB.
2. For each request: ASR gives the text. The aligner gives word timestamps. Pyannote gives the exclusive speaker turns. Each word gets the speaker of the turn that overlaps it the most.
3. Return the Gemini-style response.
4. Weights come from the weights bucket (weights-copy job), with `HF_HUB_OFFLINE=1`. The Pyannote weights need an `HF_TOKEN` with accepted conditions for the copy only.
5. Public access through API Gateway with the shared API key and the CORS proxy, as LLM-A.

Why one container and not "STT-A plus a diarization service": a second service means a second cold start and a second GPU bill. It also means the audio goes over the network 2 times. One container keeps one L4 instance per request.

## Open decisions for the user

1. Platform. `CLAUDE.md` and the 2026-11-10 decision say Vertex AI for all models except TTS-A. An older project memory (2026-11-09) says Cloud Run GPU for all models. The plan uses Vertex AI with `infra/modules/vertex-model`. Confirm.
2. Relation to the STT-A card. Option a: this card replaces STT-A (one image with ASR, aligner and diarization). Option b: build STT-A first on stock vLLM, then this card as a separate custom image.
3. Diarization model. Recommended: Pyannote community-1. Alternative: NVIDIA Sortformer v2.1 (end-to-end, 4 speakers maximum, NVIDIA license).
4. Contract depth. Full Gemini Interactions shape (`steps[].content[].annotations[]`), or only `output_text` plus a flat `words` list.
5. Languages. Speakers per word work only in the 11 aligner languages. Is that enough, or does the service need a fallback (speaker per segment) for the other languages?

## What to check before implementation

1. The `qwen-asr` package version and the vLLM version it needs. Check that the aligner runs in the same process.
2. The Pyannote community-1 Hugging Face gate, and that pyannote.audio 4.x runs offline from `/models`.
3. The Vertex AI body limit. A dedicated endpoint is necessary for audio above 1.5 MB, or send a `gs://` path.
4. Measure the RTF of all 3 steps on an L4, and the cold start.
5. Measure DER on 2 or 3 of our own recordings.

## Sources

- [Gemini 3.5 Transcribe (Google AI Studio docs)](https://aistudio.google.com/docs/transcribe)
- [Gemini audio understanding (Google AI Studio docs)](https://aistudio.google.com/docs/audio)
- [Complete guide to Gemini 3.5 Transcribe (dev.to, Google AI)](https://dev.to/googleai/stop-wrestling-with-asr-the-complete-guide-to-gemini-35-transcribe-1m6i)
- [Smart mode and diarization conflict (Gemini Lab)](https://gemilab.net/en/articles/gemini-api/gemini-35-transcribe-smart-mode-diarization-timestamp-conflict)
- [Qwen3-ASR Technical Report](https://arxiv.org/abs/2601.21337)
- [Qwen3-ForcedAligner-0.6B (Hugging Face)](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)
- [vLLM qwen3_asr_forced_aligner](https://docs.vllm.ai/en/latest/api/vllm/model_executor/models/qwen3_asr_forced_aligner/)
- [qwen-aligner-toolkit (aligner + Pyannote)](https://pypi.org/project/qwen-aligner-toolkit/)
- [Quantatirsk/qwen3-asr server](https://github.com/Quantatirsk/qwen3-asr)
- [Pyannote speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
- [Pyannote community-1 blog](https://pyannote.ai/blog/community-1)
- [Pyannote vs SpeechBrain](https://www.pyannote.ai/blog/pyannote-vs.-speechbrain-for-speaker-diarization)
- [Diarize benchmarks (CPU RTF)](https://foxnosetech.github.io/diarize/benchmarks/)
- [TitaNet paper](https://arxiv.org/abs/2110.04410)
- [NVIDIA streaming Sortformer 4spk v2.1](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1)
- [Benchmarking Diarization Models](https://arxiv.org/abs/2509.26177)
