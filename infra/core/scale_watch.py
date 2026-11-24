"""scale-watch: 1 log line when a Runpod endpoint goes from 0 to 1 or more ready workers, or back to 0.

Cloud Scheduler runs this Cloud Run job every minute (infra/core/scale_watch.tf). It reads every endpoint and model of
the accounts, compares the ready counts with the last run (STATE_BUCKET/state.json) and prints
  scale-watch: <platform> <id> ready (<name>)
  scale-watch: <platform> <id> scaled to 0 (<name>)
The log-based alerts of each deployment (alerts.tf, module scale-alerts) send these lines to Slack.
Python 3 standard library only. Key: env RUNPOD_API_KEY (Secret Manager). A missing key skips the platform.
The state keys are "<platform>/<id>", so another platform needs only one more *_counts function.
"""
import json
import os
import sys
import urllib.request
from urllib.error import HTTPError

RUNPOD = "https://api.runpod.io/v2/serverless"


def http_get(url, auth):
    req = urllib.request.Request(url, headers={"Authorization": auth, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def health_ok(url, auth):
    """True when the model answers GET /health with 200. A worker that still loads answers 204 or holds the request."""
    req = urllib.request.Request(url, headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 - not ready yet (timeout, 5xx): the next run asks again
        return False


def runpod_counts(key, prev=None, get=http_get, probe=health_ok):
    """{"runpod/<endpoint id>": (name, ready workers)} for every endpoint of the account. Up: IDLE or RUNNING with an
    uptime. A FlashBoot worker that has stopped stays in the list as IDLE without uptimeSeconds (measured 2026-11-23),
    so the summary counts are not used. A worker is up minutes before the model loads, so an endpoint that had 0 ready
    workers in the last run counts as ready only when its /health answers 200. The probe goes only to an endpoint with
    an up worker (it never wakes one at 0) and stops once it is ready (it does not keep the worker busy)."""
    auth = f"Bearer {key}"
    out = {}
    for e in get(RUNPOD, auth).get("endpoints", []):
        k = f"runpod/{e['id']}"
        workers = get(f"{RUNPOD}/{e['id']}/workers", auth).get("workers", [])
        up = sum(1 for w in workers if w.get("status") in ("IDLE", "RUNNING") and w.get("uptimeSeconds") is not None)
        if up and not (prev or {}).get(k):
            health = (e.get("requestUrls") or {}).get("health") or f"https://{e['id']}.api.runpod.ai/health"
            up = up if probe(health, auth) else 0
        out[k] = (e.get("name", ""), up)
    return out


# (platform, env var of the key, reader(key, prev counts)). Another platform needs one more entry.
PLATFORMS = (("runpod", "RUNPOD_API_KEY", runpod_counts),)


def events(prev, cur):
    """Log lines for the changes from prev ({key: count}, None on the first run) to cur ({key: (name, count)})."""
    if prev is None:
        return []
    lines = []
    for key, (name, n) in cur.items():
        platform, ident = key.split("/", 1)
        was = prev.get(key, 0)
        if was == 0 and n > 0:
            lines.append(f"scale-watch: {platform} {ident} ready ({name})")
        elif was > 0 and n == 0:
            lines.append(f"scale-watch: {platform} {ident} scaled to 0 ({name})")
    return lines


def next_state(prev, cur, failed):
    """The counts to keep. A platform that failed this run keeps its old counts, so the next run sees the change."""
    keep = {k: v for k, v in (prev or {}).items() if k.split("/", 1)[0] in failed}
    return {**keep, **{k: n for k, (_, n) in cur.items()}}


def token():
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)["access_token"]


class Conflict(Exception):
    """Another run saved the state first (two runs can overlap when one starts late)."""


def commit(lines, save):
    """The lines to print: all of them when save() wins, none when another run won (it prints the change)."""
    try:
        save()
    except Conflict:
        return []
    return lines


def load_state(bucket, tok):
    """(state or None, generation). Generation "0" means no object yet."""
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/state.json?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r), r.headers.get("x-goog-generation", "0")
    except HTTPError as e:
        if e.code == 404:
            return None, "0"
        raise


def save_state(bucket, tok, state, generation):
    """Write state.json only if nobody changed it since load_state (ifGenerationMatch), else raise Conflict."""
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name=state.json&ifGenerationMatch={generation}"
    req = urllib.request.Request(url, data=json.dumps(state).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except HTTPError as e:
        if e.code == 412:
            raise Conflict() from e
        raise


def main():
    bucket = os.environ["STATE_BUCKET"]
    tok = token()
    prev, generation = load_state(bucket, tok)
    cur, failed = {}, set()
    for platform, env, fn in PLATFORMS:
        key = os.environ.get(env, "").strip()
        if not key:
            continue
        try:
            cur.update(fn(key, prev))
        except Exception as e:  # one platform down must not stop the other; the key is never printed
            failed.add(platform)
            print(f"scale-watch warning: {platform} read failed: {type(e).__name__} {getattr(e, 'code', '')}", file=sys.stderr)
    lines = commit(events(prev, cur), lambda: save_state(bucket, tok, next_state(prev, cur, failed), generation))
    for line in lines:
        print(line, flush=True)
    print(f"scale-watch: checked {len(cur)} endpoints", flush=True)


if __name__ == "__main__":
    main()
