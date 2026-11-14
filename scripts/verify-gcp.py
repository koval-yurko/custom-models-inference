#!/usr/bin/env python3
"""Verify what is deployed in the real GCP project. Guide: .claude/skills/verify-gcp/SKILL.md.

Run from anywhere:  ./scripts/verify-gcp.py state [--plan] | smoke | call --tts | call --llm
  state   Read-only, free. Cloud Run services: min instances 0, no public invoker. Vertex AI: every deployed model
          scales to 0. API Gateway: every gateway ACTIVE. Test UI: the models.json in the UI bucket points only to
          live gateways. --plan also runs `terraform plan` (remote on HCP, read-only) in every root: it must be "No changes".
  smoke   Free, no API key, no model runs (same checks as the curl lines in the skill). For each tab in the deployed
          models.json: every route rejects a call with no key (401/403), and the CORS preflight answers with
          Access-Control-Allow-Origin. Also: the UI page and models.json load. A preflight can wake a CPU service
          (Kokoro, the CORS proxy); it never reaches Vertex AI.
  call    Costs money. Run it only when the user asks in the same message. --tts: GET voices + 1 short speech (Cloud Run
          CPU). --llm: 1 short chat (starts the L4 GPU, about $1.34/h, cold start up to 15 min, HTTP 429 until ready).
          The key comes from `terraform output` in infra/core and is never printed.
Loads the repo .env itself. Every run writes its report to .verify/gcp/<run-id>/report.txt. Exit 1 on a FAIL.
"""
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORIGIN = "https://storage.googleapis.com"  # the origin of the test UI
ROUTES = {"llm": [("POST", "/v1/chat/completions")], "tts": [("POST", "/v1/audio/speech"), ("GET", "/v1/audio/voices")]}
results, lines = [], []


def load_env():
    """Minimal .env reader (same as preflight.py). Values already in the environment win."""
    f = ROOT / ".env"
    for line in f.read_text().splitlines() if f.exists() else []:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        v = v[1:].split(v[0])[0] if v[:1] in "\"'" else v.split(" #")[0].strip()
        os.environ.setdefault(k.strip(), v)
    E = os.environ
    if E.get("GOOGLE_APPLICATION_CREDENTIALS"):
        E.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", E["GOOGLE_APPLICATION_CREDENTIALS"])
        E.setdefault("CLOUDSDK_CONFIG", str(ROOT / ".gcloud"))
    if E.get("GCP_PROJECT_ID"):
        E.setdefault("CLOUDSDK_CORE_PROJECT", E["GCP_PROJECT_ID"])


def out(text):
    print(text)
    lines.append(text)


def report(level, name, detail=""):
    results.append(level)
    out(f"  {level:<4} {name}" + (f": {detail}" if detail else ""))


def gcloud_json(*args):
    r = subprocess.run(["gcloud", *args, "--format=json"], text=True, capture_output=True)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1])
    return json.loads(r.stdout or "null")


def http(method, url, headers=None, body=None, timeout=30):
    """Return (status, headers, body bytes, seconds). Status 0 means no answer."""
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read(), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read(), time.monotonic() - t0
    except OSError as e:
        return 0, {}, str(e).encode(), time.monotonic() - t0


def ui_base():
    return f"{ORIGIN}/{os.environ['GCP_PROJECT_ID']}-ui"


def deployed_models():
    code, _, body, _ = http("GET", f"{ui_base()}/models.json")
    if code != 200:
        raise RuntimeError(f"models.json in the UI bucket: HTTP {code}")
    return json.loads(body)["models"]


def state(plan):
    region = os.environ["GCP_REGION"]
    out(f"Cloud Run ({region})")
    for s in gcloud_json("run", "services", "list", f"--region={region}"):
        n = s["metadata"]["name"]
        mins = s["spec"]["template"]["metadata"].get("annotations", {}).get("autoscaling.knative.dev/minScale", "0")
        report("ok" if mins == "0" else "FAIL", f"{n}: min instances {mins}")
        pol = gcloud_json("run", "services", "get-iam-policy", n, f"--region={region}") or {}
        public = [m for b in pol.get("bindings", []) for m in b.get("members", []) if m in ("allUsers", "allAuthenticatedUsers")]
        report("FAIL" if public else "ok", f"{n}: private", f"public members {public}" if public else "")
    out(f"Vertex AI ({region})")
    for ep in gcloud_json("ai", "endpoints", "list", f"--region={region}"):
        for m in ep.get("deployedModels", []):
            mn = m.get("dedicatedResources", {}).get("minReplicaCount", 0)
            report("ok" if mn == 0 else "FAIL", f"{ep['displayName']}: deployed model {m['id']} min replicas {mn}")
        if not ep.get("deployedModels"):
            report("WARN", f"{ep['displayName']}: no deployed model", "run scripts/vertex.py deploy <deployment>")
    out("API Gateway")
    hosts = {}
    for g in gcloud_json("api-gateway", "gateways", "list"):
        hosts[g["defaultHostname"]] = g["name"].split("/")[-1]
        report("ok" if g["state"] == "ACTIVE" else "FAIL", f"{g['name'].split('/')[-1]}: {g['state']}")
    out("Test UI config (models.json in the UI bucket)")
    models = deployed_models()
    for m in models:
        host = m["base_url"].split("://", 1)[-1].rstrip("/")
        report("ok" if host in hosts else "FAIL", f"tab {m['id']} -> {host}", "" if host in hosts else "no live gateway: run scripts/ui-deploy.py --config-only")
    for host, name in hosts.items():
        if host not in {m["base_url"].split("://", 1)[-1].rstrip("/") for m in models}:
            report("WARN", f"gateway {name} has no tab", "add a `ui` output, see the model-ui skill")
    if plan:
        out("Terraform drift (remote plan on HCP, read-only)")
        for d in [ROOT / "infra/core", *sorted((ROOT / "deployments").iterdir())]:
            if not (d / "backend.tf").exists():
                continue
            subprocess.run(["terraform", "init", "-input=false", "-no-color"], cwd=d, capture_output=True)
            r = subprocess.run(["terraform", "plan", "-detailed-exitcode", "-lock=false", "-input=false", "-no-color"], cwd=d, text=True, capture_output=True)
            summary = next((l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("Plan:", "No changes", "Error"))), "")
            report({0: "ok", 2: "FAIL"}.get(r.returncode, "WARN"), f"{d.relative_to(ROOT)}", summary or f"exit {r.returncode}")


def smoke():
    code, _, body, sec = http("GET", f"{ui_base()}/index.html")
    report("ok" if code == 200 and b"<title>Model tests</title>" in body else "FAIL", "UI page loads", f"HTTP {code}, {sec:.2f} s")
    code, hdr, _, sec = http("GET", f"{ui_base()}/models.json")
    cc = hdr.get("Cache-Control", "") if hdr else ""
    report("ok" if code == 200 and "no-cache" in cc else "FAIL", "models.json loads with no-cache", f"HTTP {code}, Cache-Control '{cc}', {sec:.2f} s")
    for m in deployed_models():
        for method, path in ROUTES.get(m["type"], []):
            url = m["base_url"] + path
            code, _, _, sec = http(method, url, {"Content-Type": "application/json"}, b"{}" if method == "POST" else None)
            report("ok" if code in (401, 403) else "FAIL", f"{m['id']} {method} {path} with no key is rejected", f"HTTP {code}, {sec:.2f} s")
            code, hdr, _, sec = http("OPTIONS", url, {"Origin": ORIGIN, "Access-Control-Request-Method": method,
                                                      "Access-Control-Request-Headers": "content-type,x-api-key"}, timeout=300)
            acao = hdr.get("Access-Control-Allow-Origin", "") if hdr else ""
            acah = (hdr.get("Access-Control-Allow-Headers", "") if hdr else "").lower()
            ok = 200 <= code < 300 and acao in ("*", ORIGIN) and ("x-api-key" in acah or "*" in acah)
            # 300 s = the gateway deadline (gateway.tf), which includes the cold start of the backend.
            level = "FAIL" if not ok else "WARN" if sec > 30 else "ok"
            report(level, f"{m['id']} OPTIONS {path} (CORS preflight)", f"HTTP {code}, allow-origin '{acao}', allow-headers '{acah}', {sec:.2f} s"
                   + (" (slow: cold start of the backend; the browser waits too)" if level == "WARN" else ""))


def api_key():
    d = ROOT / "infra/core"
    subprocess.run(["terraform", "init", "-input=false", "-no-color"], cwd=d, capture_output=True)
    r = subprocess.run(["terraform", "output", "-raw", "api_key"], cwd=d, text=True, capture_output=True)
    if r.returncode or not r.stdout:
        sys.exit("Cannot read the api_key output of infra/core (terraform init / HCP access).")
    return r.stdout.strip()


def call(tts, llm):
    key, models = api_key(), deployed_models()
    for m in models:
        h = {"x-api-key": key, "Content-Type": "application/json"}
        if tts and m["type"] == "tts":
            code, _, body, sec = http("GET", m["base_url"] + "/v1/audio/voices", h, timeout=120)
            report("ok" if code == 200 else "FAIL", f"{m['id']} voices", f"HTTP {code}, {sec:.2f} s, {len(body)} bytes")
            req = json.dumps({"model": m["model"], "input": "Verification call.", "voice": m["features"].get("default_voice", ""), "response_format": "wav"}).encode()
            code, _, body, sec = http("POST", m["base_url"] + "/v1/audio/speech", h, req, timeout=120)
            report("ok" if code == 200 and body[:4] == b"RIFF" else "FAIL", f"{m['id']} speech (wav)", f"HTTP {code}, {sec:.2f} s, {len(body)} bytes, header {body[:4]!r}")
        if llm and m["type"] == "llm":
            req = json.dumps({"model": m["model"], "messages": [{"role": "user", "content": "Say hello in 5 words."}], "max_tokens": 32}).encode()
            t0 = time.monotonic()
            for attempt in range(60):  # Vertex AI answers 429 at 0 replicas: the same rule as the UI and the README loop
                code, _, body, sec = http("POST", m["base_url"] + "/v1/chat/completions", h, req, timeout=300)
                if code != 429:
                    break
                out(f"  ...  {m['id']}: HTTP 429 (cold start), retry {attempt + 1}/60 in 30 s")
                time.sleep(30)
            text = ""
            if code == 200:
                text = json.loads(body)["choices"][0]["message"]["content"].strip()
            report("ok" if code == 200 and text else "FAIL", f"{m['id']} chat", f"HTTP {code}, {time.monotonic() - t0:.0f} s incl. cold start, answer '{text[:60]}'")


def main():
    load_env()
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd not in ("state", "smoke", "call"):
        sys.exit(__doc__)
    if cmd == "call" and not {"--tts", "--llm"} & set(args):
        sys.exit("call needs --tts and/or --llm. It costs money: run it only when the user asks.")
    run_dir = ROOT / ".verify" / "gcp" / f"{time.strftime('%Y%m%d-%H%M%S')}-{cmd}"
    run_dir.mkdir(parents=True, exist_ok=True)
    out(f"verify-gcp {cmd} {' '.join(args)}  project {os.environ.get('GCP_PROJECT_ID')}  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        if cmd == "state":
            state("--plan" in args)
        elif cmd == "smoke":
            smoke()
        else:
            call("--tts" in args, "--llm" in args)
    except RuntimeError as e:
        report("FAIL", "check could not run", str(e))
    out(f"{results.count('ok')} ok, {results.count('WARN')} warn, {results.count('FAIL')} fail. Report: {run_dir}/report.txt")
    (run_dir / "report.txt").write_text("\n".join(lines) + "\n")
    sys.exit(1 if "FAIL" in results else 0)


if __name__ == "__main__":
    main()
