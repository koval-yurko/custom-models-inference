# Pin the tag. qwen-asr 0.0.6 pins vllm==0.14.0 (see requirements.txt). The base image has torch, fastapi and uvicorn.
FROM vllm/vllm-openai:v0.14.0

# ffmpeg decodes mp3, m4a, ogg, webm and the other Gemini audio types.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
# Hold the torch and vllm of the base image: pyannote.audio must not replace them.
# blinker 1.4 comes from apt (distutils), so pip cannot replace it for flask (qwen-asr needs flask): install over it.
RUN pip install --no-cache-dir --ignore-installed blinker \
    && pip freeze | grep -iE '^(torch|torchaudio|torchvision|vllm)==' > /tmp/base.txt \
    && pip install --no-cache-dir -c /tmp/base.txt -r requirements.txt

COPY speech_engine/ speech_engine/
# The weights come from GCS (AIP_STORAGE_URI), never from the Hugging Face Hub.
ENV HF_HUB_OFFLINE=1

# 1 process: each process loads the 3 models again. speech_engine.main reads AIP_HTTP_PORT (Vertex AI sets 8080).
# This replaces the vLLM server entrypoint of the base image.
ENTRYPOINT ["python3", "-m", "speech_engine.main"]
