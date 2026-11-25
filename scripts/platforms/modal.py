"""Post-apply step of Modal: deploy (or stop) the Modal app of a deployment.

A library for scripts/deploy.py. The caller loads .env (MODAL_TOKEN_ID, MODAL_TOKEN_SECRET, HF_TOKEN, SLACK_*).
Modal has no Terraform provider. This reads `terraform output -json modal` in the deployment folder and runs the
modal CLI (a pinned version, through uvx) on the shared app file scripts/platforms/modal_app.py:
  deploy:   `modal run modal_app.py::fill` (the weights Volume from Hugging Face; files already there are skipped),
            then `modal deploy modal_app.py`.
  undeploy: `modal app stop <app>`. A stopped app answers 404 at its URL.
The image pull key is the infra/core output registry_pull_key (the read-only key of the repo models).
"""
import json, os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = pathlib.Path(__file__).with_name("modal_app.py")
MODAL = ["uvx", "--from", "modal==1.6.4", "modal"]


def tf_output(d, *args):
    r = subprocess.run(["terraform", "output", *args], cwd=d, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"terraform output {' '.join(args)} failed in {d}:\n{r.stderr}")
    return r.stdout


def spec(d):
    s = json.loads(tf_output(d, "-json", "modal"))
    if s is None:
        sys.exit(f"{d} has no modal output value (is modal in local.platforms, and is it applied?)")
    return s


def cli(args, env=None, capture=False):
    r = subprocess.run(MODAL + args, env=env, text=True, capture_output=capture)
    if r.returncode and not capture:
        sys.exit(f"modal {' '.join(args[:2])} failed (exit {r.returncode})")
    return r


def deploy_env(s, pull_key):
    """The env of the modal CLI: the spec for modal_app.py and the pull key. The rest (tokens, HF_TOKEN, Slack) is .env."""
    return {**os.environ, "MODAL_SPEC": json.dumps(s), "SERVICE_ACCOUNT_JSON": pull_key}


def deploy(d):
    s = spec(d)
    env = deploy_env(s, tf_output(ROOT / "infra" / "core", "-raw", "registry_pull_key"))
    if s["hf_repos"]:
        cli(["run", f"{APP}::fill"], env)
    cli(["deploy", str(APP)], env)


def is_deployed(apps, name):
    return any(a.get("description") == name and a.get("state") == "deployed" for a in apps)


def undeploy(d):
    s = spec(d)
    r = cli(["app", "list", "--json"], capture=True)
    if r.returncode == 0 and not is_deployed(json.loads(r.stdout), s["app"]):
        return print(f"modal: app {s['app']} is not deployed")
    cli(["app", "stop", s["app"], "--yes"])


def deployed(d):
    r = cli(["app", "list", "--json"], capture=True)
    if r.returncode:
        sys.exit(f"modal app list failed:\n{r.stderr}")
    return is_deployed(json.loads(r.stdout), spec(d)["app"])
