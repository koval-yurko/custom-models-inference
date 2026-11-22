"""Evaluation: score each transcript version against the reference (the correct transcript) of its file.
Computed on read, not stored. Standard library only. No LLM: the scores are exact word and time counts.

  reference.py  check and store format of a reference; time parsing
  metrics.py    the standard metrics: WER (edit distance), cpWER (CHiME-6), DER (frames, collar)
  scoring.py    1 version against its reference, and the mean per setup over all files
"""
