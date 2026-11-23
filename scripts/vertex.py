#!/usr/bin/env python3
"""Post-apply step: upload and deploy (or undeploy and delete) the model of a vertex-model deployment.

Run from anywhere:  ./scripts/vertex.py deploy|undeploy deployments/<name>   (loads the repo .env itself; no direnv needed)
For a deployment on infra/modules/model (it has a targets output), use ./scripts/deploy.py instead.
Terraform cannot do it: the provider has no resource for a custom-container model upload or for a deployed model.
The code is in scripts/platforms/vertex.py. It reads `terraform output -json vertex` and calls the Vertex AI REST API (v1beta1).
Run `deploy` after terraform apply. Run `undeploy` before terraform destroy.
At the end it runs `ui-deploy.py --config-only`, so the test UI shows the tab only while a model is deployed.
"""
import os, pathlib, subprocess, sys

from platforms import vertex


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


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("deploy", "undeploy"):
        sys.exit(f"usage: {sys.argv[0]} deploy|undeploy deployments/<name>")
    d = (pathlib.Path.cwd() / sys.argv[2]).resolve()
    load_env()
    env_like_envrc()
    vertex.deploy(d) if sys.argv[1] == "deploy" else vertex.undeploy(d)
    # The UI shows a Vertex AI tab only while its endpoint has a deployed model.
    subprocess.run([str(ROOT / "scripts" / "ui-deploy.py"), "--config-only"], cwd=ROOT)
