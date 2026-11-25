#!/usr/bin/env python3
"""Post-apply step of every platform of a model deployment (the targets output of infra/modules/model).

Run from anywhere (loads the repo .env itself; no direnv needed):
  ./scripts/deploy.py deploy   deployments/<name> [--platform <id>]   # after terraform apply
  ./scripts/deploy.py undeploy deployments/<name> [--platform <id>]   # before terraform destroy, or before you remove a platform
  ./scripts/deploy.py status   deployments/<name> [--platform <id>]   # deployed or not, per platform
It reads `terraform output -json platforms` and `targets`. A target with post_apply runs scripts/platforms/<post_apply>.py
(vertex: model upload and deploy; modal: modal deploy). A target without post_apply (runpod) is ready after apply.
deploy and undeploy run `ui-deploy.py --config-only` at the end, so the test UI follows each change.
It does not run terraform apply or destroy.
"""
import importlib, json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


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


def output(d, name):
    r = subprocess.run(["terraform", "output", "-json", name], cwd=d, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"terraform output {name} failed in {d} (a deployment on infra/modules/model, applied?):\n{r.stderr}")
    return json.loads(r.stdout)


def select(platforms, targets, only):
    """Targets in the order of platforms. With only: the one target. An unknown id exits."""
    if only is not None and only not in platforms:
        sys.exit(f"unknown platform {only}; this model has: {', '.join(platforms)}")
    return [targets[p] for p in platforms if only in (None, p)]


def step(t):
    """The post-apply module of a target, or None."""
    return importlib.import_module(f"platforms.{t['post_apply']}") if t.get("post_apply") else None


def main(argv):
    only = None
    if "--platform" in argv:
        i = argv.index("--platform")
        only = argv[i + 1] if i + 1 < len(argv) else sys.exit("--platform needs an id")
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 2 or argv[0] not in ("deploy", "undeploy", "status"):
        sys.exit(f"usage: {sys.argv[0]} deploy|undeploy|status deployments/<name> [--platform <id>]")
    cmd, d = argv[0], (pathlib.Path.cwd() / argv[1]).resolve()
    load_env()
    env_like_envrc()
    for t in select(output(d, "platforms"), output(d, "targets"), only):
        mod = step(t)
        if cmd == "status":
            print(f"{t['id']}: {'deployed' if mod is None or mod.deployed(d) else 'not deployed'}")
        elif mod is None:
            print(f"{t['id']}: nothing to do (ready after terraform apply)")
        else:
            print(f"{t['id']}: {cmd}")
            getattr(mod, cmd)(d)
    if cmd != "status":
        subprocess.run([str(ROOT / "scripts" / "ui-deploy.py"), "--config-only"], cwd=ROOT)


if __name__ == "__main__":
    main(sys.argv[1:])
