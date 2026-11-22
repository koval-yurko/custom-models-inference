# STT-A STT API service: standard library only, so the stock slim image is enough (no pip install).
FROM python:3.13.9-slim

WORKDIR /srv
COPY stt_api/ stt_api/
ENV PYTHONUNBUFFERED=1
# No root: the service only calls Google APIs over HTTPS.
USER nobody

# server.py reads PORT (Cloud Run sets 8080) and the env from ../../stt_api.tf.
CMD ["python3", "-m", "stt_api"]
