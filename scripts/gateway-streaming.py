#!/usr/bin/env python3
"""Post-apply step: give the API Gateway of a deployment streaming (chunked responses, SSE).

Run from anywhere:  ./scripts/gateway-streaming.py deployments/tts-a-kokoro-cpu [--yes]   (loads the repo .env itself; no direnv needed)
Terraform cannot do it: the provider has no streaming field, and the API sets it only at create time.
The script replaces the gateway with a streaming gateway that has the same ID. Then it imports the gateway into
the Terraform state if the state does not have it, and refreshes the state. It does nothing when the gateway
already streams. It uses the REST API (v1 streamingMode) because older gcloud versions have no --enable-streaming flag.
"""
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "https://apigateway.googleapis.com/v1"


def load_env():
    """Minimal .env reader (same as hcp-sync.py). Values already in the environment win."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v[:1] in "\"'":
            v = v[1:].split(v[0])[0]
        else:
            v = v.split(" #")[0].strip()
        os.environ.setdefault(k.strip(), v)


def env_like_envrc():
    """The parts of .envrc that terraform and gcloud need here."""
    E = os.environ
    for var, key in {"project_id": "GCP_PROJECT_ID", "region": "GCP_REGION", "invoker_email": "INVOKER_EMAIL"}.items():
        if E.get(key):
            E.setdefault(f"TF_VAR_{var}", E[key])
    if E.get("GOOGLE_APPLICATION_CREDENTIALS"):
        E.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", E["GOOGLE_APPLICATION_CREDENTIALS"])
        E.setdefault("CLOUDSDK_CONFIG", str(ROOT / ".gcloud"))


def run(*cmd, capture=True):
    r = subprocess.run(cmd, cwd=DIR, text=True, capture_output=capture)
    if r.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{r.stderr if capture else ''}")
    return r.stdout.strip() if capture else ""


def call(method, path, body=None):
    """REST call. Returns (HTTP code, JSON body)."""
    req = urllib.request.Request(f"{BASE}/{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}


def ok(method, path, body=None):
    code, d = call(method, path, body)
    if code != 200:
        sys.exit(f"{method} {path} returned {code}: {d}")
    return d


def wait(op, minutes=20):
    for _ in range(minutes * 6):
        d = ok("GET", op)
        if d.get("done"):
            if "error" in d:
                sys.exit(f"operation {op} failed: {d['error']}")
            return
        time.sleep(10)
    sys.exit(f"Timeout: operation {op} is not done")


def main():
    gw, loc, cfg = (run("terraform", "output", "-raw", o) for o in ("gateway_id", "gateway_region", "api_config"))
    project = cfg.split("/")[1]  # projects/<p>/locations/global/apis/<api>/configs/<id>
    name = f"projects/{project}/locations/{loc}/gateways/{gw}"

    def create():
        print(f"Creating streaming gateway {name} ...")
        wait(ok("POST", f"projects/{project}/locations/{loc}/gateways?gatewayId={gw}",
                {"apiConfig": cfg, "streamingMode": "STREAMING_MODE_ENABLED"})["name"])

    code, d = call("GET", name)
    if code == 200 and d.get("effectiveStreamingMode") == "EFFECTIVE_STREAMING_MODE_ENABLED":
        print(f"Gateway {name} already streams.")
    elif code == 200:
        if "--yes" not in sys.argv and input(f"Delete {name} and make it again with streaming? "
                                             "The gateway URL changes. [y/N] ") != "y":
            sys.exit(1)
        wait(ok("DELETE", name)["name"])
        create()
    elif code == 404:
        create()
    else:
        sys.exit(f"GET {name} returned {code}: {d}")

    d = ok("GET", name)
    if d.get("effectiveStreamingMode") != "EFFECTIVE_STREAMING_MODE_ENABLED":
        sys.exit(f"Gateway does not stream: {d}")
    print(f"Gateway URL: https://{d['defaultHostname']}")

    if "google_api_gateway_gateway.this" not in run("terraform", "state", "list").splitlines():
        run("terraform", "import", "google_api_gateway_gateway.this", name, capture=False)
    # Read the new hostname into the state. A refresh-only run changes nothing in GCP.
    run("terraform", "apply", "-refresh-only", "-auto-approve", capture=False)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(f"usage: {sys.argv[0]} deployments/<name> [--yes]")
    DIR = (pathlib.Path.cwd() / args[0]).resolve()
    load_env()
    env_like_envrc()
    TOKEN = run("gcloud", "auth", "print-access-token")
    main()
