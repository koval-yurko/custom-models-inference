#!/usr/bin/env python3
"""Post-apply step: upload and deploy (or undeploy and delete) the model of a vertex-model deployment.

Run from anywhere:  ./scripts/vertex.py deploy|undeploy deployments/<name>   (loads the repo .env itself; no direnv needed)
Terraform cannot do it: the provider has no resource for a custom-container model upload or for a deployed model.
The script reads `terraform output -json vertex` and calls the Vertex AI REST API (v1beta1).
Run `deploy` after terraform apply. Run `undeploy` before terraform destroy.
At the end it runs `ui-deploy.py --config-only`, so the test UI shows the tab only while a model is deployed.
"""
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.request


ROOT = pathlib.Path(__file__).resolve().parent.parent


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


def run(*cmd):
    r = subprocess.run(cmd, cwd=DIR, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"{' '.join(cmd)} failed:\n{r.stderr}")
    return r.stdout.strip()


def drop_nulls(x):
    """Same as jq `del(.. | nulls)`: the API rejects null fields."""
    if isinstance(x, dict):
        return {k: drop_nulls(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [drop_nulls(v) for v in x if v is not None]
    return x


def call(method, path, body=None, retry=True):
    """REST call. Exits with the HTTP code and the error body on a failure. On a 401 it gets a new token once (a token lasts 1 hour)."""
    global TOKEN
    req = urllib.request.Request(f"{API}/{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry:
            TOKEN = run("gcloud", "auth", "print-access-token")
            return call(method, path, body, retry=False)
        sys.exit(f"{method} {path} returned {e.code}: {e.read().decode()[:800]}")


def wait(op):
    """Wait for a long-running operation (max 60 min: deploymentTimeout max is 1800 s plus node start)."""
    for _ in range(240):
        d = call("GET", op)
        if d.get("done"):
            if "error" in d:
                sys.exit(f"operation failed: {json.dumps(d['error'])}")
            return d
        time.sleep(15)
    sys.exit(f"timeout waiting for {op}")


def deployed_ids():
    return [m["id"] for m in call("GET", V["endpoint"]).get("deployedModels", [])]


def warm_cache():
    """Fetch the image manifest once. For a remote proxy repo (dockerhub, ghcr) this fills the cache; Vertex AI does not start the fetch itself."""
    uri = V["model_upload"]["model"]["containerSpec"]["imageUri"]
    host, _, rest = uri.partition("/")
    if not host.endswith("-docker.pkg.dev"):
        return
    path, _, tag = rest.rpartition(":")
    project, repo, image = path.split("/", 2)
    # Multi-arch lists (stock Docker Hub images) and single manifests (own Cloud Build images).
    accept = ("application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,"
              "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json")
    req = urllib.request.Request(f"https://{host}/v2/{project}/{repo}/{image}/manifests/{tag}",
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": accept})
    print(f"Fill the image cache for {uri}...")
    try:
        urllib.request.urlopen(req).close()
    except urllib.error.HTTPError as e:
        sys.exit(f"Image cache fill returned {e.code}: {e.read().decode()[:400]}")


def deploy():
    if deployed_ids():
        sys.exit(f"The endpoint already has a deployed model. Run '{sys.argv[0]} undeploy {sys.argv[2]}' first.")
    warm_cache()
    # A failed deploy leaves the uploaded model. Reuse it. `undeploy` deletes it, so a changed image or args start clean.
    flt = f"models?filter=display_name=%22{V['name']}%22"
    old = call("GET", f"projects/{V['project']}/locations/{V['region']}/{flt}").get("models", [])
    if old:
        model = old[0]["name"]
        print(f"Reuse the uploaded model (run undeploy first to upload it again after a config change).")
    else:
        print(f"Upload model {V['name']}...")
        model = wait(call("POST", f"projects/{V['project']}/locations/{V['region']}/models:upload",
                          drop_nulls(V["model_upload"]))["name"])["response"]["model"]
    print(f"Model: {model}")
    print(f"Deploy to {V['endpoint']} (min 0 replicas). This can take 30 minutes...")
    body = {"deployedModel": drop_nulls({**V["deployed_model"], "model": model}), "trafficSplit": {"0": 100}}
    d = wait(call("POST", f"{V['endpoint']}:deployModel", body)["name"])
    print(f"Deployed model ID: {d['response']['deployedModel']['id']}")
    print(f"Endpoint DNS: {V['endpoint_dns']}")


def undeploy():
    for i in deployed_ids():
        print(f"Undeploy {i}...")
        wait(call("POST", f"{V['endpoint']}:undeployModel", {"deployedModelId": i})["name"])
    # Delete every model with this display name, also one left behind by a failed deploy.
    flt = f"models?filter=display_name=%22{V['name']}%22"
    for m in call("GET", f"projects/{V['project']}/locations/{V['region']}/{flt}").get("models", []):
        print(f"Delete {m['name']}...")
        wait(call("DELETE", m["name"])["name"])
    print("Done. Run terraform destroy to remove the endpoint and the service account.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("deploy", "undeploy"):
        sys.exit(f"usage: {sys.argv[0]} deploy|undeploy deployments/<name>")
    DIR = (pathlib.Path.cwd() / sys.argv[2]).resolve()
    load_env()
    env_like_envrc()
    V = json.loads(run("terraform", "output", "-json", "vertex"))
    API = f"https://{V['region']}-aiplatform.googleapis.com/v1beta1"
    TOKEN = run("gcloud", "auth", "print-access-token")
    deploy() if sys.argv[1] == "deploy" else undeploy()
    # The UI shows a Vertex AI tab only while its endpoint has a deployed model.
    subprocess.run([str(ROOT / "scripts" / "ui-deploy.py"), "--config-only"], cwd=ROOT)
