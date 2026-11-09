#!/usr/bin/env python3
"""Sync .env values to the HCP Terraform workspaces of this repo.

Run from anywhere:  ./scripts/hcp-sync.py [--dry-run]   (it loads the repo .env itself; no direnv needed)
Needs: TF_CLOUD_ORGANIZATION, TF_CLOUD_PROJECT, TF_TOKEN_app_terraform_io, GOOGLE_APPLICATION_CREDENTIALS.
Creates the workspaces if missing, sets remote execution, and upserts the variables. Never prints values.
"""
import json, os, pathlib, sys, urllib.request, urllib.error


def load_env():
    """Minimal .env reader. Values already in the environment win. Handles quotes and ' # comment'."""
    f = pathlib.Path(__file__).resolve().parent.parent / ".env"
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


load_env()

DRY = "--dry-run" in sys.argv
ORG = os.environ["TF_CLOUD_ORGANIZATION"]
PROJECT = os.environ["TF_CLOUD_PROJECT"]
TOKEN = os.environ["TF_TOKEN_app_terraform_io"]
BASE = "https://app.terraform.io/api/v2"
E = os.environ.get

# workspace -> (working directory, terraform variables). A variable is skipped when its .env value is empty.
COMMON = {"project_id": E("GCP_PROJECT_ID"), "region": E("GCP_REGION")}
WORKSPACES = {
    "custom-models-bootstrap": ("", {**COMMON, "billing_account": E("BILLING_ACCOUNT"), "budget_amount": E("BUDGET_AMOUNT"),
                                      "hf_token": E("HF_TOKEN")}),
    # Deployments use the shared module outside their folder, so the CLI uploads the repo root.
    "custom-models-tts-a-kokoro-cpu": ("deployments/tts-a-kokoro-cpu", {**COMMON, "invoker_email": E("INVOKER_EMAIL")}),
    "custom-models-llm-a-gemma4-12b-vllm": ("deployments/llm-a-gemma4-12b-vllm", {**COMMON, "invoker_email": E("INVOKER_EMAIL")}),
}
SENSITIVE = {"hf_token", "GOOGLE_CREDENTIALS"}


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/vnd.api+json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r) if r.length != 0 else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"HCP API {method} {path} failed: {e.code} {e.read().decode()[:300]}")


def find_project():
    d = api("GET", f"/organizations/{ORG}/projects?filter%5Bnames%5D={PROJECT}")
    for p in d["data"]:
        if p["attributes"]["name"] == PROJECT:
            return p["id"]
    sys.exit(f"HCP project '{PROJECT}' not found in organization '{ORG}'. Create it first.")


def ensure_workspace(name, workdir, project_id):
    attrs = {"name": name, "execution-mode": "remote", "working-directory": workdir, "terraform-version": ">= 1.11"}
    d = None
    try:
        d = api("GET", f"/organizations/{ORG}/workspaces/{name}")
    except SystemExit:
        pass
    if d and "data" in d:
        ws = d["data"]["id"]
        print(f"{name}: exists, updating settings")
        if not DRY:
            api("PATCH", f"/workspaces/{ws}", {"data": {"type": "workspaces", "attributes": attrs}})
        return ws
    print(f"{name}: creating in project {PROJECT}")
    if DRY:
        return None
    body = {"data": {"type": "workspaces", "attributes": attrs,
                     "relationships": {"project": {"data": {"type": "projects", "id": project_id}}}}}
    return api("POST", f"/organizations/{ORG}/workspaces", body)["data"]["id"]


def upsert(ws, existing, key, value, category):
    attrs = {"key": key, "value": value, "category": category, "sensitive": key in SENSITIVE, "hcl": False}
    print(f"  {category}:{key}{' (sensitive)' if key in SENSITIVE else ''}{' [update]' if (category, key) in existing else ' [create]'}")
    if DRY or ws is None:
        return
    body = {"data": {"type": "vars", "attributes": attrs}}
    if (category, key) in existing:
        body["data"]["id"] = existing[(category, key)]
        api("PATCH", f"/workspaces/{ws}/vars/{existing[(category, key)]}", body)
    else:
        api("POST", f"/workspaces/{ws}/vars", body)


def main():
    key_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = json.dumps(json.load(open(key_path)), separators=(",", ":"))
    project_id = find_project()
    for name, (workdir, tfvars) in WORKSPACES.items():
        ws = ensure_workspace(name, workdir, project_id)
        existing = {}
        if ws:
            for v in api("GET", f"/workspaces/{ws}/vars")["data"]:
                existing[(v["attributes"]["category"], v["attributes"]["key"])] = v["id"]
        upsert(ws, existing, "GOOGLE_CREDENTIALS", creds, "env")
        for k, v in tfvars.items():
            if v:
                upsert(ws, existing, k, v, "terraform")
    print("Done." + (" (dry run, nothing changed)" if DRY else ""))


if __name__ == "__main__":
    main()
