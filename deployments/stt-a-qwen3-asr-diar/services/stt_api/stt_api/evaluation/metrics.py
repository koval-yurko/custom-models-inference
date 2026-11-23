"""Standard speech-to-text metrics, standard library only.
  WER    word edit distance / reference words (text only)
  cpWER  CHiME-6: words joined per speaker, best speaker mapping (Hungarian method) (text and speakers)
  DER    diarization error rate: 10 ms frames, 0.25 s collar (who spoke when)
"""
import re

COLLAR, FRAME = 0.25, 0.01


def norm_words(text):
    """Lowercase, no punctuation, split on spaces. "Don't stop, Bob!" -> ["dont", "stop", "bob"]."""
    return re.sub(r"[^\w\s]", " ", text.lower().replace("'", "").replace("’", "")).split()


def edit_distance(a, b):
    """Word Levenshtein distance. Bit-parallel (Myers 1999, Hyyro 2001) on Python ints: O(len(b)) int operations,
    so a 30-minute file (5000 words) takes milliseconds, not the minutes of the O(n*m) table in pure Python."""
    if not a:
        return len(b)
    peq = {}
    for i, w in enumerate(a):
        peq[w] = peq.get(w, 0) | 1 << i
    mask, top = (1 << len(a)) - 1, 1 << (len(a) - 1)
    pv, mv, score = mask, 0, len(a)
    for w in b:
        eq = peq.get(w, 0)
        xv = eq | mv
        xh = (((eq & pv) + pv) ^ pv) | eq
        ph = mv | (~(xh | pv) & mask)
        mh = pv & xh
        score += (1 if ph & top else -1 if mh & top else 0)
        ph = ((ph << 1) | 1) & mask  # | 1: row 0 of the table counts up (global distance, not a search)
        mh = (mh << 1) & mask
        pv = mh | (~(xv | ph) & mask)
        mv = ph & xv
    return score


def assign(cost):
    """Hungarian method, O(n^3): square cost matrix -> the column of each row with the lowest total cost."""
    n, inf = len(cost), float("inf")
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0, minv, used = i, 0, [inf] * (n + 1), [False] * (n + 1)
        while p[j0]:
            used[j0], i0, delta, j1 = True, p[j0], inf, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
        while j0:
            j1 = way[j0]
            p[j0], j0 = p[j1], j1
    cols = [0] * n
    for j in range(1, n + 1):
        cols[p[j] - 1] = j - 1
    return cols


def _match(rows, cols, cost):
    """Best 1:1 match of rows to cols (lists of keys), padded with empty rows/cols. -> ({col: row}, total cost)."""
    n = max(len(rows), len(cols))
    m = [[cost(rows[i] if i < len(rows) else None, cols[j] if j < len(cols) else None) for j in range(n)]
         for i in range(n)]
    best = assign(m) if n else []
    pairs = {cols[j]: rows[i] for i, j in enumerate(best) if i < len(rows) and j < len(cols)}
    return pairs, sum(m[i][j] for i, j in enumerate(best))


def _by_speaker(items):
    out = {}
    for spk, ws in items:
        out.setdefault(spk, []).extend(ws)
    return out


def cp_wer(ref, hyp):
    """CHiME-6 cpWER. ref, hyp: [(speaker, [words])]. The words of each speaker are joined; each hyp speaker maps to at
    most 1 ref speaker so that the total errors are lowest. -> (cpWER, {hyp speaker: ref speaker})."""
    r, h = _by_speaker(ref), _by_speaker(hyp)
    pairs, errors = _match(list(r), list(h), lambda a, b: edit_distance(r.get(a, []), h.get(b, [])))
    return errors / sum(len(w) for w in r.values()), pairs


def der(ref, hyp, collar=COLLAR, frame=FRAME):
    """Diarization error rate. ref, hyp: [(speaker, start s, end s)]. Frames within the collar of a ref boundary are
    not scored. -> {der, missed, false_alarm, confusion}, each a share of the scored ref speaker time."""
    f = lambda t: int(round(t / frame))  # noqa: E731
    n, c = max((f(e) for _, _, e in ref + hyp), default=0), f(collar)
    scored = bytearray([1]) * n
    for _, s, e in ref:
        for b in (f(s), f(e)):
            scored[max(0, b - c):b + c] = bytes(len(scored[max(0, b - c):b + c]))

    def frames(segs):  # speaker bits per frame
        keys = sorted({s for s, _, _ in segs})
        out = [0] * n
        for spk, s, e in segs:
            bit = 1 << keys.index(spk)
            for i in range(f(s), f(e)):
                out[i] |= bit
        return keys, out

    rk, rf = frames(ref)
    hk, hf = frames(hyp)
    total = missed = fa = both = 0
    pair_frames = {}
    for i in range(n):
        if not scored[i]:
            continue
        nr, nh = rf[i].bit_count(), hf[i].bit_count()
        total, missed, fa, both = total + nr, missed + max(0, nr - nh), fa + max(0, nh - nr), both + min(nr, nh)
        if nr and nh:
            pair_frames[rf[i], hf[i]] = pair_frames.get((rf[i], hf[i]), 0) + 1
    overlap = {}
    for (rb, hb), k in pair_frames.items():
        for a in range(len(rk)):
            for b in range(len(hk)):
                if rb >> a & 1 and hb >> b & 1:
                    overlap[a, b] = overlap.get((a, b), 0) + k
    _, neg = _match(list(range(len(rk))), list(range(len(hk))), lambda a, b: -overlap.get((a, b), 0))
    conf = both + neg  # neg = -(frames where the mapped hyp speaker is right)
    if not total:
        return None
    return {"der": (missed + fa + conf) / total, "missed": missed / total, "false_alarm": fa / total,
            "confusion": conf / total}
