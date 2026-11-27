#!/usr/bin/env python3
"""Read-only checks against the real project before an apply or a Vertex AI deploy.

Run from anywhere:  ./scripts/preflight.py [--weights <folder>] [--l4]   (loads the repo .env itself; no direnv needed)
Checks: the shell and the HCP workspace variables match .env, the needed APIs are on, the buckets and the Artifact Registry repos
are in GCP_REGION, the weights folder has files (--weights), the Vertex AI L4 quota is 1 or more (--l4), and the prepaid
Runpod balance (when RUNPOD_API_KEY is set): below $0.01 Runpod starts no worker and refuses an endpoint create, without an error
on the call. It cannot see Vertex AI GPU stock: no API shows it. Runpod GPU stock: see the deployment README (Test).
Exit 1 on a FAIL. A WARN means the script could not check.
"""
import argparse, json, os, pathlib, re, subprocess, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEEDED_APIS = ["aiplatform", "run", "artifactregistry", "storage", "apigateway", "secretmanager", "apikeys", "iamcredentials"]
results = []


DOTENV = {}


def load_env():
    """Minimal .env reader (same as vertex.py). Values already in the environment win. DOTENV keeps the file values."""
    f = ROOT / ".env"
    for line in f.read_text().splitlines() if f.exists() else []:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        v = v[1:].split(v[0])[0] if v[:1] in "\"'" else v.split(" #")[0].strip()
        DOTENV[k.strip()] = v
        os.environ.setdefault(k.strip(), v)
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        os.environ.setdefault("CLOUDSDK_CONFIG", str(ROOT / ".gcloud"))
    # Like .envrc: gcloud calls without --project need it, so the script runs without direnv.
    if os.environ.get("GCP_PROJECT_ID"):
        os.environ.setdefault("CLOUDSDK_CORE_PROJECT", os.environ["GCP_PROJECT_ID"])


def sh(*cmd):
    r = subprocess.run(cmd, text=True, capture_output=True)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stdout + r.stderr).strip()


def report(level, name, detail=""):
    results.append(level)
    print(f"  {level:<4} {name}" + (f": {detail}" if detail else ""))


def check_env_and_hcp(region):
    stale = [k for k in ("GCP_PROJECT_ID", "GCP_REGION") if k in DOTENV and os.environ.get(k) != DOTENV[k]]
    if stale:
        report("FAIL", "shell is stale", f"{', '.join(stale)} differ from .env: run 'direnv reload' or start a new shell")
    # shortcut: HCP variable values are read from the API for the workspaces named in backend.tf. Sensitive variables are not compared.
    org, token = os.environ.get("TF_CLOUD_ORGANIZATION"), os.environ.get("TF_TOKEN_app_terraform_io")
    if not org or not token:
        return report("WARN", "HCP region variable", "TF_CLOUD_ORGANIZATION or TF_TOKEN_app_terraform_io is not set")
    names = sorted({m for f in [ROOT / "infra/core/backend.tf", *ROOT.glob("deployments/*/backend.tf")]
                    for m in re.findall(r'name\s*=\s*"([^"]+)"', f.read_text())})
    wrong = []
    for n in names:
        try:
            ws = hcp(f"organizations/{org}/workspaces/{n}", token)["data"]["id"]
            vals = [v["attributes"]["value"] for v in hcp(f"workspaces/{ws}/vars", token)["data"] if v["attributes"]["key"] == "region"]
        except urllib.error.HTTPError as e:
            return report("WARN", "HCP region variable", f"{n}: HTTP {e.code}")
        if vals != [region]:
            wrong.append(f"{n}={vals[0] if vals else 'missing'}")
    report("FAIL" if wrong else "ok", "HCP region variable", "differs from .env, run ./scripts/hcp-sync.py: " + ", ".join(wrong) if wrong else "")


def hcp(path, token):
    req = urllib.request.Request(f"https://app.terraform.io/api/v2/{path}", headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req))


def check_apis():
    rc, out = sh("gcloud", "services", "list", "--enabled", "--format=value(config.name)")
    if rc:
        return report("WARN", "APIs", out[:200])
    missing = [a for a in NEEDED_APIS if f"{a}.googleapis.com" not in out.split()]
    report("FAIL" if missing else "ok", "APIs enabled", "missing: " + ", ".join(missing) if missing else "")


def check_region(project, region):
    rc, out = sh("gcloud", "storage", "buckets", "describe", f"gs://{project}-models", "--format=value(location)")
    if rc:
        report("FAIL", "weights bucket", f"gs://{project}-models not found: apply infra/core")
    else:
        report("ok" if out.lower() == region.lower() else "FAIL", "weights bucket region", f"{out} (GCP_REGION={region})")
    rc, out = sh("gcloud", "artifacts", "repositories", "list", "--format=json")
    repos = [r["name"] for r in json.loads(out)] if rc == 0 else []
    wrong = [r.split("/")[-1] for r in repos if f"/locations/{region}/" not in r]
    if rc or not repos:
        report("FAIL", "Artifact Registry repos", out[:100] if rc else "none found: apply infra/core")
    else:
        report("FAIL" if wrong else "ok", "Artifact Registry repos in region", "wrong region: " + ", ".join(wrong) if wrong else "")


def check_weights(project, folder):
    rc, out = sh("gcloud", "storage", "ls", f"gs://{project}-models/{folder}/")
    report("ok" if rc == 0 and out else "FAIL", f"weights in {folder}/", "" if rc == 0 and out else "empty: run the weights-copy job")


def check_l4(project, region):
    _, token = sh("gcloud", "auth", "print-access-token")
    url = f"https://cloudquotas.googleapis.com/v1/projects/{project}/locations/global/services/aiplatform.googleapis.com/quotaInfos?pageSize=500"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project})
    try:
        infos = json.load(urllib.request.urlopen(req)).get("quotaInfos", [])
    except urllib.error.HTTPError as e:
        hint = "run: gcloud services enable cloudquotas.googleapis.com" if e.code == 403 else f"HTTP {e.code}"
        return report("WARN", "L4 quota", f"cannot read ({hint}); check the console: IAM & Admin > Quotas")
    # shortcut: the quota id is matched by name. Check the id if Google renames it (list: quotaInfos of aiplatform.googleapis.com).
    vals = [d["details"].get("value", "0") for q in infos if q["quotaId"] == "CustomModelServingL4GPUsPerProjectPerRegion"
            for d in q.get("dimensionsInfos", []) if d.get("dimensions", {}).get("region") == region]
    if not vals:
        return report("WARN", "L4 quota", f"no entry for {region}; check the console")
    report("ok" if any(int(v) >= 1 for v in vals) else "FAIL", f"L4 quota in {region}", "values: " + ", ".join(vals))


def runpod_level(amount):
    """FAIL below $0.01 (no worker starts, endpoint create fails), WARN below $1 (1 GPU test costs up to about $0.50)."""
    return "FAIL" if amount < 0.01 else "WARN" if amount < 1 else "ok"


def check_runpod_balance():
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        return
    req = urllib.request.Request("https://api.runpod.io/v2/billing/balance", headers={"Authorization": f"Bearer {key}"})
    try:
        amount = float(json.load(urllib.request.urlopen(req, timeout=20))["balanceAmount"])
    except Exception as e:  # noqa: BLE001 - a check that cannot run is a WARN
        return report("WARN", "Runpod balance", f"cannot read ({e}); check the Runpod console > Billing")
    report(runpod_level(amount), "Runpod balance", f"${amount:.2f} (prepaid; top up in the Runpod console > Billing)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", help="folder in the weights bucket, for example gemma-4-12b-it-qat-w4a16")
    ap.add_argument("--l4", action="store_true", help="check the Vertex AI L4 quota")
    a = ap.parse_args()
    load_env()
    project, region = os.environ.get("GCP_PROJECT_ID"), os.environ.get("GCP_REGION")
    if not project or not region:
        sys.exit("Set GCP_PROJECT_ID and GCP_REGION in .env.")
    print(f"project {project}, region {region}")
    check_env_and_hcp(region)
    check_apis()
    check_region(project, region)
    check_runpod_balance()
    if a.weights:
        check_weights(project, a.weights)
    if a.l4:
        check_l4(project, region)
    sys.exit(1 if "FAIL" in results else 0)
