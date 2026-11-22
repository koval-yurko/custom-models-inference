"""The main work of STT-A: decode the audio, find the speaker turns, transcribe each turn, time each word.

Pyannote finds the turns first. Qwen3-ASR transcribes each turn, and each word gets the speaker of its turn.
The aligner times the words in its 11 languages; other languages get estimated times. The rules (turns, request,
answer) are in logic.py; the 3 real models are in models.py. Spec: docs/specs/2026-11-21-stt-a-design.md.
"""
from __future__ import annotations

import subprocess
import tempfile
import traceback
from typing import Protocol

import numpy as np

from speech_engine.logic import (
    ALIGNER_LANGS, LANGS, BadRequest, Job, Turn, Word, build_response, check_duration, estimate_words,
    label_speakers, longest_clip, make_turns,
)

SR = 16000
NAMES = frozenset(LANGS.values())


class Models(Protocol):
    def diarize(self, audio: np.ndarray, sr: int) -> list[tuple[float, float, str]]: ...
    def transcribe(self, clips: list[np.ndarray], sr: int, language: str | None) -> list[tuple[str, str]]: ...
    def align(self, clip: np.ndarray, sr: int, text: str, language: str) -> list[Word]: ...
    def read_gcs(self, uri: str) -> bytes: ...


def decode(data: bytes, max_seconds: float = 1801) -> tuple[np.ndarray, int]:
    """Any ffmpeg format to 16 kHz mono float32. A file, not a pipe: m4a and mp4 need a seekable input.
    -t stops after max_seconds (1 s over the check_duration limit), so a very long upload does not decode in full."""
    with tempfile.NamedTemporaryFile() as f:
        f.write(data)
        f.flush()
        p = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", f.name, "-t", str(max_seconds),
                            "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        raise BadRequest(f"audio does not decode: {p.stderr.decode(errors='replace').strip()[:200]}")
    return np.frombuffer(p.stdout, np.float32), SR


def _cut(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    return audio[int(start * sr):int(end * sr)]


def _first_name(language: str) -> str | None:
    name = (language or "").split(",")[0].strip()
    return name if name in NAMES else None


def _word_times(m: Models, turn: Turn, clip: np.ndarray, sr: int, text: str, language: str | None) -> list[Word]:
    if not text:
        return []
    if language in ALIGNER_LANGS:
        try:
            aligned = m.align(clip, sr, text, language)
            if aligned:
                return [Word(w.text, round(w.start + turn.start, 3), round(w.end + turn.start, 3)) for w in aligned]
        except Exception:  # noqa: BLE001 - estimated times are better than HTTP 500
            traceback.print_exc()
    return estimate_words(text, turn.start, turn.end)


def transcribe(m: Models, job: Job) -> dict:
    audio, sr = decode(job.data if job.data is not None else m.read_gcs(job.gcs_uri))
    total = len(audio) / sr
    check_duration(total)
    turns = make_turns(m.diarize(audio, sr) if job.diarize else [], total, job.diarize)
    if not turns:
        return {**build_response([], [], [], {}, job), "audio_seconds": round(total, 3)}
    language = job.language
    if language is None:  # detect 1 time: short turns detect badly
        start, end = longest_clip(turns)
        language = _first_name(m.transcribe([_cut(audio, sr, start, end)], sr, None)[0][1])
    clips = [_cut(audio, sr, t.start, t.end) for t in turns]
    results = m.transcribe(clips, sr, language)
    texts = [text.strip() for text, _ in results]
    if job.diarize or job.words:  # only annotations need word times: skip the aligner (GPU time) otherwise
        words = [_word_times(m, t, c, sr, text, language or _first_name(lang))
                 for t, c, text, (_, lang) in zip(turns, clips, texts, results)]
    else:
        words = [[] for _ in turns]
    return {**build_response(turns, texts, words, label_speakers(turns), job), "audio_seconds": round(total, 3)}
