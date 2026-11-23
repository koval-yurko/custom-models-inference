"""Score 1 version against its reference, and sum the scores per setup over all files with a reference."""
import json

from stt_api.bucket import ID_RE, NAMES, REFERENCE
from stt_api.evaluation.metrics import cp_wer, der, edit_distance, norm_words
from stt_api.evaluation.reference import seconds

SEG_GAP = 1.0  # hyp words more than 1 s apart start a new segment (DER)


def hyp_words(version):
    """Version -> [(speaker, [normalized words], start s | None, end s | None)], 1 item per word_info."""
    resp = version.get("response") or {}
    try:
        notes = resp["steps"][0]["content"][0].get("annotations") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        notes = []
    if not notes:
        return [("", norm_words(resp.get("output_text") or ""), None, None)]
    out = []
    for w in notes:
        try:
            times = seconds(w["start_offset"]), seconds(w["end_offset"])
        except (KeyError, ValueError):
            times = None, None
        out.append((w.get("speaker") or "", norm_words(w.get("text") or ""), *times))
    return out


def hyp_segments(words):
    """Consecutive words of 1 speaker -> 1 segment; a gap over SEG_GAP starts a new one. None when a time is missing."""
    segs = []
    for spk, _, s, e in words:
        if s is None:
            return None
        if segs and segs[-1][0] == spk and s - segs[-1][2] <= SEG_GAP:
            segs[-1][2] = max(segs[-1][2], e)
        else:
            segs.append([spk, s, e])
    return [tuple(x) for x in segs]


def setup_label(version):
    s = version.get("setup")
    if not isinstance(s, dict):
        return "unknown"
    label = f"{s.get('asr', '?')} + {s.get('aligner', '?')} + {s.get('diarization', '?')} @ {s.get('image_tag', '?')}"
    # Versions from before the Runpod platform have no platform or gpu: their label stays as it was.
    where = " ".join(x for x in (s.get("platform"), s.get("gpu")) if x)
    return f"{label} on {where}" if where else label


def score(reference, version):
    """1 version against the reference of its file. All rates are shares (0.12 = 12 %)."""
    ref = [(t["speaker"], norm_words(t["text"])) for t in reference["turns"]]
    hw = hyp_words(version)
    hyp = [(spk, ws) for spk, ws, _, _ in hw]
    n_ref = sum(len(ws) for _, ws in ref)
    cp, pairs = cp_wer(ref, hyp)
    timed = all("start" in t for t in reference["turns"])
    segs = hyp_segments(hw)
    d = der([(t["speaker"], seconds(t["start"]), seconds(t["end"])) for t in reference["turns"]], segs) \
        if timed and segs is not None else None
    resp = version.get("response") or {}
    audio_s = resp.get("audio_seconds") or max((e for *_, e in hw if e is not None), default=None)
    run_s = version.get("run_seconds")
    settings = version.get("settings") or {}
    return {
        "version_id": version.get("id"), "setup": setup_label(version), "settings": settings,
        "wer": edit_distance([w for _, ws in ref for w in ws], [w for _, ws in hyp for w in ws]) / n_ref,
        "cpwer": cp, "mapping": pairs, "der": d, "ref_words": n_ref,
        "ref_speakers": len({s for s, _ in ref}), "hyp_speakers": len({s for s, ws in hyp if s}),
        "speed": round(audio_s / run_s, 2) if audio_s and run_s else None,
    }


def group_key(row):
    """Setup plus the request settings that change the result (no diarization, a fixed language)."""
    s = row["settings"]
    extra = ([] if s.get("diarization", True) else ["no diarization"]) + \
            ([f"language {','.join(s['language_codes'])}"] if s.get("language_codes") else [])
    return " · ".join([row["setup"], *extra])


def summarize(rows):
    """Score rows -> 1 row per setup: mean WER, cpWER and DER (DER over the versions that have it)."""
    groups = {}
    for r in rows:
        groups.setdefault(group_key(r), []).append(r)
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return [{"setup": k, "versions": len(g), "files": len({r["file_id"] for r in g}),
             "wer": mean([r["wer"] for r in g]), "cpwer": mean([r["cpwer"] for r in g]),
             "der": mean([r["der"]["der"] for r in g if r["der"]])}
            for k, g in sorted(groups.items())]


def all_scores(store):
    """Every version of every file with a reference. shortcut: reads 1 object at a time; add threads if it gets slow."""
    objs = store.list("files/")
    names = {o["name"].split("/")[1]: (o.get("metadata") or {}).get("name", "") for o in objs
             if o["name"].endswith("/meta.json")}
    rows = []
    for o in objs:
        parts = o["name"].split("/")
        if len(parts) != 3 or parts[2] != REFERENCE or not ID_RE.match(parts[1]):
            continue
        ref = json.loads(store.read(o["name"]))
        for v in objs:
            vp = v["name"].split("/")
            if len(vp) == 4 and vp[1] == parts[1] and vp[2] == "versions" and vp[3].endswith(".json") \
                    and not vp[3].endswith(NAMES):
                rows.append({"file_id": parts[1], "file_name": names.get(parts[1], ""),
                             **score(ref, json.loads(store.read(v["name"])))})
    return {"rows": rows, "setups": summarize(rows)}
