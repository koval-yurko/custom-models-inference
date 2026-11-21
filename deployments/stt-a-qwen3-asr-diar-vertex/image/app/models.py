"""The 3 real models on the L4 GPU. No unit test: it needs the GPU and the weights. API checked against qwen-asr 0.0.6
and pyannote.audio 4.1.1 (pins in requirements.txt)."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from google.cloud import storage

from app.logic import Word

# /models is read-only in the Vertex AI container, so the weights go to the writable local disk.
ROOT = Path("/tmp/models")


def _split_uri(uri: str) -> tuple[str, str]:
    bucket, _, name = uri.removeprefix("gs://").partition("/")
    return bucket, name


def copy_weights(client: storage.Client, uri: str) -> None:
    """Copy gs://<models bucket>/stt-a-qwen3-asr-diar/{asr,aligner,pyannote}/ to ROOT on local disk."""
    bucket, prefix = _split_uri(uri.rstrip("/") + "/")
    for blob in client.list_blobs(bucket, prefix=prefix):
        if blob.name.endswith("/") or "/.cache/" in blob.name:  # .cache: leftovers of the weights-copy job
            continue
        dest = ROOT / blob.name[len(prefix):]
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))


class RealModels:
    def __init__(self):
        import torch
        from pyannote.audio import Pipeline
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

        self.torch = torch
        self.gcs = storage.Client()
        # Vertex AI sets AIP_STORAGE_URI from artifactUri. Without it (local run), ROOT must hold the 3 folders.
        if os.environ.get("AIP_STORAGE_URI"):
            copy_weights(self.gcs, os.environ["AIP_STORAGE_URI"])
        # vLLM first: it starts its engine process before the other 2 models use CUDA in this process.
        # A turn is at most 180 s of audio, so 16384 tokens is plenty; the full 65536 does not fit in half an L4.
        self.asr = Qwen3ASRModel.LLM(model=str(ROOT / "asr"), max_new_tokens=4096,
                                     gpu_memory_utilization=float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.5")),
                                     max_model_len=int(os.environ.get("MAX_MODEL_LEN", "16384")))
        self.aligner = Qwen3ForcedAligner.from_pretrained(str(ROOT / "aligner"), dtype=torch.bfloat16,
                                                          device_map="cuda:0")
        self.pipeline = Pipeline.from_pretrained(str(ROOT / "pyannote"))
        self.pipeline.to(torch.device("cuda"))

    def diarize(self, audio: np.ndarray, sr: int) -> list[tuple[float, float, str]]:
        out = self.pipeline({"waveform": self.torch.from_numpy(audio).unsqueeze(0), "sample_rate": sr},
                            max_speakers=8)
        return [(seg.start, seg.end, spk)
                for seg, _, spk in out.exclusive_speaker_diarization.itertracks(yield_label=True)]

    def transcribe(self, clips: list[np.ndarray], sr: int, language: str | None) -> list[tuple[str, str]]:
        results = self.asr.transcribe(audio=[(c, sr) for c in clips], language=language)
        return [(r.text, r.language) for r in results]

    def align(self, clip: np.ndarray, sr: int, text: str, language: str) -> list[Word]:
        result = self.aligner.align(audio=(clip, sr), text=text, language=language)[0]
        return [Word(i.text, float(i.start_time), float(i.end_time)) for i in result.items]

    def read_gcs(self, uri: str) -> bytes:
        bucket, name = _split_uri(uri)
        return self.gcs.bucket(bucket).blob(name).download_as_bytes()
