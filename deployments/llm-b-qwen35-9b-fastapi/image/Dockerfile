# Pin the tag. app.py uses the vLLM Python API of this version (AsyncLLM, StructuredOutputsParams).
# The base image has fastapi, uvicorn and the runai model streamer (gs:// load) already.
FROM vllm/vllm-openai:v0.33.0

WORKDIR /app
COPY app.py .

# 1 process: each process loads the model again. app.py reads AIP_HTTP_PORT (Vertex AI sets 8080).
ENTRYPOINT ["python3", "/app/app.py"]
