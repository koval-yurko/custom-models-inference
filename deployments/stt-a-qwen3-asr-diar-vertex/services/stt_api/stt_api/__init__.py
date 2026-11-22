"""STT-A STT API service: uploads, file list, transcript history, "transcribe again" and the evaluation scores.

CPU only and standard library only, so a client gets a URL or the history without a GPU cold start.
Spec: docs/specs/2026-11-21-stt-a-design.md, sections "STT API service" and "Evaluation".

Modules:
  server.py      HTTP server (CORS, JSON in and out); __main__.py starts it from the env
  routes.py      the route table: 1 function that maps (method, path, body) to (status, JSON)
  files.py       uploads and transcript history: request checks, file list, version summaries, speaker names
  bucket.py      the bucket layout: object names and id formats
  gcp.py         Google Cloud calls: GCS store, V4 signed URLs, the GPU :rawPredict call, tokens
  evaluation/    the scores of a version against the reference transcript of its file (extra, not the main flow)
"""
