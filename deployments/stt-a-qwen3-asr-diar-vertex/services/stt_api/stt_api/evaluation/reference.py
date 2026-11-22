"""The reference of a file: {"language", "turns": [{"speaker", "text", "start"?, "end"?}]}. Check it and read times."""
import math

from stt_api.evaluation.metrics import norm_words
from stt_api.files import MAX_NAME

MAX_TURNS, MAX_TURN_TEXT, MAX_LANG = 20_000, 20_000, 20


def seconds(value):
    """12.5, "12.5", "12.5s", "01:02.5" or "00:01:02.5" -> 62.5 s."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"bad time {value!r}")
    t = 0.0
    try:
        for part in (str(value).strip().removesuffix("s").split(":") if isinstance(value, str) else [value]):
            t = t * 60 + float(part)
    except ValueError:
        raise ValueError(f"bad time {value!r}: use seconds or hh:mm:ss.s") from None
    if not math.isfinite(t) or t < 0 or (isinstance(value, str) and value.count(":") > 2):
        raise ValueError(f"bad time {value!r}: use seconds or hh:mm:ss.s")
    return t


def check_reference(body):
    """{"language": "en", "turns": [{"speaker", "text", "start"?, "end"?}]} -> the object to store."""
    if not isinstance(body, dict) or not isinstance(body.get("turns"), list) or not 1 <= len(body["turns"]) <= MAX_TURNS:
        raise ValueError(f"body must be a JSON object with 1 to {MAX_TURNS} turns")
    lang = body.get("language", "")
    if not isinstance(lang, str) or len(lang) > MAX_LANG:
        raise ValueError(f"language must be a string of 0 to {MAX_LANG} chars")
    turns = []
    for i, t in enumerate(body["turns"]):
        if not isinstance(t, dict):
            raise ValueError(f"turn {i + 1} must be an object")
        spk, text = t.get("speaker"), t.get("text")
        if not isinstance(spk, str) or not 1 <= len(spk.strip()) <= MAX_NAME:
            raise ValueError(f"turn {i + 1}: speaker must be a string of 1 to {MAX_NAME} chars")
        if not isinstance(text, str) or len(text) > MAX_TURN_TEXT:
            raise ValueError(f"turn {i + 1}: text must be a string of 0 to {MAX_TURN_TEXT} chars")
        turn = {"speaker": spk.strip(), "text": text}
        if ("start" in t) != ("end" in t):
            raise ValueError(f"turn {i + 1}: give both start and end, or neither")
        if "start" in t:
            try:
                start, end = seconds(t["start"]), seconds(t["end"])
            except ValueError as e:
                raise ValueError(f"turn {i + 1}: {e}") from None
            if end < start:
                raise ValueError(f"turn {i + 1}: end is before start")
            turn.update(start=t["start"], end=t["end"])
        turns.append(turn)
    if not any(norm_words(t["text"]) for t in turns):
        raise ValueError("the reference has no words")
    return {"language": lang, "turns": turns}
