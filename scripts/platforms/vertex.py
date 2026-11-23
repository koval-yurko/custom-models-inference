"""Post-apply step of Vertex AI: upload and deploy (or undeploy and delete) the model of a deployment.

A library for scripts/deploy.py, scripts/vertex.py and scripts/ui-deploy.py. The caller loads .env.
Terraform cannot do it: the provider has no resource for a custom-container model upload or for a deployed model.
It reads `terraform output -json vertex` in the deployment folder and calls the Vertex AI REST API (v1beta1).
"""
import json, pathlib, subprocess, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Ctx:
    """The vertex output, the API base and the access token (refreshed on a 401) of one deployment."""

    def __init__(self, d):
        self.d = d
        self.v = json.loads(self.run("terraform", "output", "-json", "vertex"))
        self.api = f"https://{self.v['region']}-aiplatform.googleapis.com/v1beta1"
        self.token = self.run("gcloud", "auth", "print-access-token")

    def run(self, *cmd):
        r = subprocess.run(cmd, cwd=self.d, text=True, capture_output=True)
        if r.returncode:
            sys.exit(f"{' '.join(cmd)} failed:\n{r.stderr}")
        return r.stdout.strip()

    def call(self, method, path, body=None, retry=True):
        """REST call. Exits with the HTTP code and the error body on a failure. On a 401 it gets a new token once (a token lasts 1 hour)."""
        req = urllib.request.Request(f"{self.api}/{path}", method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # a long operation is polled, so no call waits long
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                self.token = self.run("gcloud", "auth", "print-access-token")
                return self.call(method, path, body, retry=False)
            sys.exit(f"{method} {path} returned {e.code}: {e.read().decode()[:800]}")

    def wait(self, op):
        """Wait for a long-running operation (max 60 min: deploymentTimeout max is 1800 s plus node start)."""
        for _ in range(240):
            d = self.call("GET", op)
            if d.get("done"):
                if "error" in d:
                    sys.exit(f"operation failed: {json.dumps(d['error'])}")
                return d
            time.sleep(15)
        sys.exit(f"timeout waiting for {op}")

    def deployed_ids(self):
        return [m["id"] for m in self.call("GET", self.v["endpoint"]).get("deployedModels", [])]

    def models(self):
        """Uploaded models with the display name of this deployment."""
        flt = f"models?filter=display_name=%22{self.v['name']}%22"
        return self.call("GET", f"projects/{self.v['project']}/locations/{self.v['region']}/{flt}").get("models", [])

    def warm_cache(self):
        """Fetch the image manifest once. For a remote proxy repo (dockerhub, ghcr) this fills the cache; Vertex AI does not start the fetch itself."""
        uri = self.v["model_upload"]["model"]["containerSpec"]["imageUri"]
        host, _, rest = uri.partition("/")
        if not host.endswith("-docker.pkg.dev"):
            return
        path, _, tag = rest.rpartition(":")
        project, repo, image = path.split("/", 2)
        # Multi-arch lists (stock Docker Hub images) and single manifests (own Cloud Build images).
        accept = ("application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,"
                  "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json")
        req = urllib.request.Request(f"https://{host}/v2/{project}/{repo}/{image}/manifests/{tag}",
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": accept})
        print(f"Fill the image cache for {uri}...")
        try:
            urllib.request.urlopen(req).close()
        except urllib.error.HTTPError as e:
            sys.exit(f"Image cache fill returned {e.code}: {e.read().decode()[:400]}")


def drop_nulls(x):
    """Same as jq `del(.. | nulls)`: the API rejects null fields."""
    if isinstance(x, dict):
        return {k: drop_nulls(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [drop_nulls(v) for v in x if v is not None]
    return x


def deploy(d):
    c = _Ctx(d)
    V = c.v
    if c.deployed_ids():
        rel = d.relative_to(ROOT) if d.is_relative_to(ROOT) else d
        sys.exit(f"The endpoint already has a deployed model. Run './scripts/deploy.py undeploy {rel} --platform vertex' first"
                 f" (a deployment without the model module: './scripts/vertex.py undeploy {rel}').")
    c.warm_cache()
    # A failed deploy leaves the uploaded model. Reuse it. `undeploy` deletes it, so a changed image or args start clean.
    old = c.models()
    if old:
        model = old[0]["name"]
        print("Reuse the uploaded model (run undeploy first to upload it again after a config change).")
    else:
        print(f"Upload model {V['name']}...")
        model = c.wait(c.call("POST", f"projects/{V['project']}/locations/{V['region']}/models:upload",
                              drop_nulls(V["model_upload"]))["name"])["response"]["model"]
    print(f"Model: {model}")
    print(f"Deploy to {V['endpoint']} (min 0 replicas). This can take 30 minutes...")
    body = {"deployedModel": drop_nulls({**V["deployed_model"], "model": model}), "trafficSplit": {"0": 100}}
    r = c.wait(c.call("POST", f"{V['endpoint']}:deployModel", body)["name"])
    print(f"Deployed model ID: {r['response']['deployedModel']['id']}")
    print(f"Endpoint DNS: {V['endpoint_dns']}")


def undeploy(d):
    c = _Ctx(d)
    for i in c.deployed_ids():
        print(f"Undeploy {i}...")
        c.wait(c.call("POST", f"{c.v['endpoint']}:undeployModel", {"deployedModelId": i})["name"])
    # Delete every model with this display name, also one left behind by a failed deploy.
    for m in c.models():
        print(f"Delete {m['name']}...")
        c.wait(c.call("DELETE", m["name"])["name"])
    print("Done. Run terraform destroy to remove the endpoint and the service account.")


def deployed(d):
    """True when the endpoint has a deployed model."""
    return bool(_Ctx(d).deployed_ids())
