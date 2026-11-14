#!/usr/bin/env python3
"""Pre-apply checks for every Terraform root: fmt, validate, test (mock provider) and tflint.

Run from anywhere:  ./scripts/check.py [path ...]   (default: infra/core, infra/modules/*, deployments/*)
No GCP credentials needed. Exits 1 when a check fails. It cannot find real-world errors (quota, stock, timing).
tflint is optional: the check is skipped with a note when it is not installed (see .tflint.hcl).
"""
import pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tf(d, *args):
    r = subprocess.run(["terraform", *args], cwd=d, text=True, capture_output=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def name(d):
    return str(d.relative_to(ROOT)) if d.is_relative_to(ROOT) else str(d)


def check(d):
    """Return a list of failure texts for one root."""
    fails = []

    def step(what, ok, out):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            fails.append(f"{name(d)}: {what}\n{out}")

    step("fmt", *tf(d, "fmt", "-check", "-diff"))
    # Do not touch a root that is already initialised (remote backend). Only add providers when they are missing.
    if not (d / ".terraform" / "providers").exists():
        step("init", *tf(d, "init", "-backend=false", "-input=false"))
    step("validate", *tf(d, "validate"))
    if (d / "tests").is_dir():
        step("test", *tf(d, "test"))
    if shutil.which("tflint"):
        r = subprocess.run(["tflint", "-c", str(ROOT / ".tflint.hcl")], cwd=d, text=True, capture_output=True)
        step("tflint", r.returncode == 0, (r.stdout + r.stderr).strip())
    return fails


def roots(args):
    if args:
        return [(pathlib.Path.cwd() / a).resolve() for a in args]
    found = [ROOT / "infra" / "core", *sorted((ROOT / "infra" / "modules").iterdir()), *sorted((ROOT / "deployments").iterdir())]
    return [d for d in found if d.is_dir() and list(d.glob("*.tf"))]


if __name__ == "__main__":
    if not shutil.which("tflint"):
        print("note: tflint is not installed, lint skipped (see .tflint.hcl)")
    failures = []
    for d in roots(sys.argv[1:]):
        print(name(d))
        failures += check(d)
    if failures:
        sys.exit("\n\n".join(["", *failures, f"{len(failures)} check(s) failed."]))
    print("All checks passed.")
