"""The 3 real models on the L4 GPU. No unit test: it needs the GPU and the weights. API checked against qwen-asr 0.0.6
and pyannote.audio 4.1.1 (pins in requirements.txt)."""
from __future__ import annotations

import os
import urllib.request

import numpy as np
from google.cloud import storage
from google.cloud.storage import transfer_manager

from speech_engine.logic import WEIGHTS_COPY_ROOT, Word, weights_root

def _split_uri(uri: str) -> tuple[str, str]:
    bucket, _, name = uri.removeprefix("gs://").partition("/")
    return bucket, name


def copy_weights(client: storage.Client, uri: str) -> None:
    """Copy gs://<models bucket>/stt-a-qwen3-asr-diar/{asr,aligner,pyannote}/ to WEIGHTS_COPY_ROOT on local disk."""
    bucket, prefix = _split_uri(uri.rstrip("/") + "/")
    names = [b.name[len(prefix):] for b in client.list_blobs(bucket, prefix=prefix)
             if not b.name.endswith("/") and "/.cache/" not in b.name]  # .cache: leftovers of the weights-copy job
    # Parallel downloads cut the cold start. Threads: the work is network I/O, and no process starts before vLLM.
    transfer_manager.download_many_to_path(client.bucket(bucket), names, destination_directory=str(WEIGHTS_COPY_ROOT),
                                           blob_name_prefix=prefix, worker_type=transfer_manager.THREAD,
                                           max_workers=16, raise_exception=True)


class RealModels:
    def __init__(self):
        import torch
        from pyannote.audio import Pipeline
        from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

        self.torch = torch
        self.gpu = torch.cuda.get_device_name(0)  # in the setup record: a Runpod pool gives an L4, an A5000 or a 3090
        root, uri = weights_root(os.environ)
        # Only with a gs:// source: on Runpod there are no GCP credentials, and the audio comes as a signed URL.
        self.gcs = storage.Client() if uri else None
        if uri:
            copy_weights(self.gcs, uri)
        # vLLM first: it starts its engine process before the other 2 models use CUDA in this process.
        # A turn is at most 180 s of audio, so 16384 tokens is plenty; the full 65536 does not fit in half an L4.
        self.asr = Qwen3ASRModel.LLM(model=str(root / "asr"), max_new_tokens=4096,
                                     gpu_memory_utilization=float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.5")),
                                     max_model_len=int(os.environ.get("MAX_MODEL_LEN", "16384")))
        self.aligner = Qwen3ForcedAligner.from_pretrained(str(root / "aligner"), dtype=torch.bfloat16,
                                                          device_map="cuda:0")
        self.pipeline = Pipeline.from_pretrained(str(root / "pyannote"))
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

    def read_audio(self, uri: str) -> bytes:
        """logic.py checked the URI: gs://<AUDIO_BUCKET>/... or a signed https://storage.googleapis.com/ URL."""
        if uri.startswith("https://"):
            with urllib.request.urlopen(uri, timeout=120) as r:
                return r.read()
        if self.gcs is None:
            self.gcs = storage.Client()
        bucket, name = _split_uri(uri)
        return self.gcs.bucket(bucket).blob(name).download_as_bytes()
