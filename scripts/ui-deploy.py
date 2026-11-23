#!/usr/bin/env python3
"""Build models.json from the `ui` output of each deployment, build the test UI and upload it.

Run from anywhere:  ./scripts/ui-deploy.py [--local | --config-only]   (loads the repo .env itself; no direnv needed)
  (no flag)      models.json + npm build + upload all to gs://<GCP_PROJECT_ID>-ui (infra/core/ui.tf)
  --config-only  models.json + upload only models.json (after a gateway URL change: no rebuild)
  --local        models.json in ui/public only (for `cd ui && npm run dev`)
A deployment is in the UI when its outputs.tf has `output "ui"` and its state has the output (it was applied).
A Vertex AI deployment (it has `output "vertex"`) is in the UI only when its endpoint has a deployed model.
A deployment on infra/modules/model (its `ui` output has `platforms`) keeps only the deployed platforms
(scripts/deploy.py status: the post-apply step says so, or the platform has no post-apply step). No platform left: no tab.
scripts/deploy.py (and scripts/vertex.py) deploy and undeploy run `--config-only` at the end, so the tabs follow each change.
Run again after every apply or scripts/gateway-streaming.py:
both can change the gateway URL. Schema of the output: .claude/skills/model-ui/SKILL.md.
"""
import json, os, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deploy  # noqa: E402
from platforms import vertex  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "ui"


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
    """The parts of .envrc that gcloud needs here."""
    E = os.environ
    if E.get("GOOGLE_APPLICATION_CREDENTIALS"):
        E.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", E["GOOGLE_APPLICATION_CREDENTIALS"])
        E.setdefault("CLOUDSDK_CONFIG", str(ROOT / ".gcloud"))
    if E.get("GCP_PROJECT_ID"):
        E.setdefault("CLOUDSDK_CORE_PROJECT", E["GCP_PROJECT_ID"])


def run(*cmd, cwd=ROOT):
    print("$", " ".join(cmd))
    if subprocess.run(cmd, cwd=cwd).returncode:
        sys.exit(f"{' '.join(cmd)} failed")


def has_deployed_model(d, out_tf):
    """False only when Vertex AI says the endpoint has no deployed model. Cloud Run (no vertex output): always True."""
    if 'output "vertex"' not in out_tf:
        return True
    try:
        return vertex.deployed(d)
    except (Exception, SystemExit) as e:  # keep the tab: a failed check must not hide a deployed model
        print(f"warn {d.name}: cannot read the Vertex AI deploy state ({e}). Keep the tab.")
        return True


def keep_deployed(entry, deployed):
    """The entry with only its deployed platforms, base_url on the first one kept. None: no platform left.
    An entry without platforms (old ui output) comes back unchanged."""
    if "platforms" not in entry:
        return entry
    kept = [p for p in entry["platforms"] if deployed.get(p["id"], True)]
    return {**entry, "base_url": kept[0]["base_url"], "platforms": kept} if kept else None


def platform_deployed(d, targets):
    """Platform id -> deployed. A failed check keeps the platform: it must not hide a deployed model."""
    out = {}
    for p, t in targets.items():
        mod = deploy.step(t)
        try:
            out[p] = mod is None or bool(mod.deployed(d))
        except (Exception, SystemExit) as e:
            print(f"warn {d.name}: cannot read the deploy state of {p} ({e}). Keep the platform.")
            out[p] = True
    return out


def tf_output(d, name):
    return subprocess.run(["terraform", "output", "-no-color", "-json", name], cwd=d, text=True, capture_output=True)


def collect():
    models = []
    for d in sorted((ROOT / "deployments").iterdir()):
        out = d / "outputs.tf"
        out_tf = out.read_text() if out.exists() else ""
        if 'output "ui"' not in out_tf:
            continue
        # init is read-only here: it connects the dir to its HCP workspace (state), so `output` can read it.
        subprocess.run(["terraform", "init", "-input=false", "-no-color"], cwd=d, capture_output=True)
        r = tf_output(d, "ui")
        if r.returncode:
            reason = next((l for l in r.stderr.splitlines() if l.startswith("Error")), r.stderr.strip()[:200])
            print(f"skip {d.name}: {reason} (apply the deployment first: a new output is in the state only after apply)")
            continue
        entry = json.loads(r.stdout)
        if "platforms" in entry:
            t = tf_output(d, "targets")
            entry = keep_deployed(entry, platform_deployed(d, json.loads(t.stdout)) if not t.returncode else {})
            if entry is None:
                print(f"skip {d.name}: no deployed platform (run scripts/deploy.py deploy {d.relative_to(ROOT)})")
                continue
        elif not has_deployed_model(d, out_tf):
            print(f"skip {d.name}: no deployed model on the Vertex AI endpoint (run scripts/deploy.py deploy {d.relative_to(ROOT)})")
            continue
        models.append(entry)
        ids = f" ({', '.join(p['id'] for p in entry['platforms'])})" if "platforms" in entry else ""
        print(f"add  {d.name}: {entry['base_url']}{ids}")
    return models


def main():
    load_env()
    env_like_envrc()
    mode = (sys.argv[1:] or [""])[0]
    if mode not in ("", "--local", "--config-only"):
        sys.exit(__doc__)

    config = UI / "public" / "models.json"
    config.write_text(json.dumps({"models": collect()}, indent=2) + "\n")
    print(f"wrote {config.relative_to(ROOT)}")
    if mode == "--local":
        return

    bucket = f"gs://{os.environ['GCP_PROJECT_ID']}-ui"
    if mode == "--config-only":
        run("gcloud", "storage", "cp", str(config), f"{bucket}/models.json", "--cache-control=no-cache")
    else:
        run("npm", "ci", cwd=UI)
        run("npm", "run", "build", cwd=UI)  # copies public/models.json into dist/
        run("gcloud", "storage", "rsync", str(UI / "dist"), bucket, "--recursive", "--delete-unmatched-destination-objects")
        # Asset names have a content hash, so they can stay in the cache. These 2 files must not.
        run("gcloud", "storage", "objects", "update", f"{bucket}/index.html", f"{bucket}/models.json", "--cache-control=no-cache")
    print(f"UI: https://storage.googleapis.com/{bucket[5:]}/index.html")


if __name__ == "__main__":
    main()
