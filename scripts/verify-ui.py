#!/usr/bin/env python3
"""Start, check and stop a disposable test UI (ui/) against the local mock gateways, for verification.

Run from anywhere:  ./scripts/verify-ui.py up | doctor | down
  up      npm ci when ui/node_modules is missing, pick 2 free ports, write ui/public/models.json for the mock,
          start the mock (ui/mock-server.mjs) and Vite, wait until both answer. Prints the UI URL and the run dir.
  doctor  Read-only. Checks that this run's processes are alive, own their ports and serve this run's config.
  down    Stops only the processes that `up` started, restores ui/public/models.json. Keeps the run dir (evidence).
No GCP, no .env, no cost. The API key of the mock is "test". Guide: .claude/skills/verify-ui/SKILL.md.
One run per checkout (ui/public/models.json is shared). Use another git worktree for a parallel run.
"""
import json, os, pathlib, shutil, signal, socket, subprocess, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
MODELS = UI / "public" / "models.json"
RUNS = ROOT / ".verify" / "ui"
CURRENT = RUNS / "current.json"
KEY = "test"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(url, key=None, method="GET"):
    """Return (status, body). Status 0 means no answer."""
    req = urllib.request.Request(url, method=method, headers={"x-api-key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except OSError:
        return 0, ""


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def listeners(port):
    r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
    return {int(p) for p in r.stdout.split()}


def load_state():
    if not CURRENT.exists():
        sys.exit("No active run (.verify/ui/current.json is missing). Run: ./scripts/verify-ui.py up")
    return json.loads(CURRENT.read_text())


def checks(st):
    """[(ok, text)]: the doctor checks. Read-only."""
    ui, mock = f"http://127.0.0.1:{st['ui_port']}", f"http://127.0.0.1:{st['mock_port']}"
    out = []
    for name in ("mock", "vite"):
        pid, port = st[f"{name}_pid"], st[f"{'mock' if name == 'mock' else 'ui'}_port"]
        out.append((alive(pid), f"{name} process {pid} is alive"))
        out.append((pid in listeners(port), f"{name} process {pid} owns port {port}"))
    code, body = http(f"{ui}/")
    out.append((code == 200 and "<title>" in body, f"Vite serves the UI at {ui}/ (HTTP {code})"))
    code, body = http(f"{ui}/models.json")
    try:
        urls = {m["base_url"] for m in json.loads(body)["models"]}
    except (ValueError, KeyError, TypeError):
        urls = set()
    out.append((urls == {mock}, f"models.json of this run points every tab to {mock} (found {sorted(urls) or 'nothing'})"))
    code, _ = http(f"{mock}/v1/audio/voices", key=KEY)
    out.append((code == 200, f"mock answers with key '{KEY}' (HTTP {code})"))
    code, _ = http(f"{mock}/v1/audio/voices", key="wrong")
    out.append((code == 403, f"mock rejects a wrong key (HTTP {code})"))
    return out


def up():
    if CURRENT.exists():
        st = json.loads(CURRENT.read_text())
        if alive(st["mock_pid"]) or alive(st["vite_pid"]):
            sys.exit(f"A run is active: {st['run_dir']}. Run ./scripts/verify-ui.py down first.")
        CURRENT.unlink()  # stale pointer: its processes are gone
    if not (UI / "node_modules" / ".bin" / "vite").exists():
        subprocess.run(["npm", "ci"], cwd=UI, check=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS / run_id
    (run_dir / "evidence").mkdir(parents=True)
    mock_port, ui_port = free_port(), free_port()
    mock = f"http://127.0.0.1:{mock_port}"
    if MODELS.exists():  # restore it in `down`, so a developer's own config survives the run
        shutil.copy2(MODELS, run_dir / "models.json.backup")
    cfg = json.loads((UI / "public" / "models.mock.json").read_text())
    for m in cfg["models"]:
        m["base_url"] = mock
    MODELS.write_text(json.dumps(cfg, indent=1))
    shutil.copy2(MODELS, run_dir / "models.json")

    def start(cmd, log, env=None):
        f = open(run_dir / log, "w")
        return subprocess.Popen(cmd, cwd=UI, stdout=f, stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, **(env or {})})

    pm = start(["node", "mock-server.mjs"], "mock.log", {"MOCK_PORT": str(mock_port)})
    pv = start(["node_modules/.bin/vite", "--host", "127.0.0.1", "--port", str(ui_port), "--strictPort"], "vite.log")
    st = {"run_id": run_id, "run_dir": str(run_dir), "mock_port": mock_port, "ui_port": ui_port, "mock_pid": pm.pid, "vite_pid": pv.pid,
          "ui_url": f"http://127.0.0.1:{ui_port}/", "mock_url": mock, "key": KEY}
    CURRENT.write_text(json.dumps(st, indent=1))
    (run_dir / "state.json").write_text(json.dumps(st, indent=1))
    for _ in range(60):  # ready = every doctor check passes, not only "a port answers"
        if all(ok for ok, _ in checks(st)):
            print(json.dumps(st, indent=1))
            print(f"READY {st['ui_url']}  key: {KEY}  evidence: {run_dir}/evidence/")
            return
        if pm.poll() is not None or pv.poll() is not None:
            break
        time.sleep(0.5)
    for ok, text in checks(st):
        print("ok  " if ok else "FAIL", text)
    print(f"Not ready. Logs: {run_dir}/mock.log, {run_dir}/vite.log. Run ./scripts/verify-ui.py down.")
    sys.exit(1)


def doctor():
    st = load_state()
    res = checks(st)
    for ok, text in res:
        print("ok  " if ok else "FAIL", text)
    print(f"run {st['run_id']}: {st['ui_url']}  evidence: {st['run_dir']}/evidence/")
    sys.exit(0 if all(ok for ok, _ in res) else 1)


def down():
    st = load_state()
    for name in ("vite", "mock"):
        pid = st[f"{name}_pid"]
        # Kill only our own process group (start_new_session=True made pid the group leader).
        if alive(pid) and os.getpgid(pid) == pid:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(20):
                if not alive(pid):
                    break
                time.sleep(0.25)
            else:
                os.killpg(pid, signal.SIGKILL)
        print(f"stopped {name} ({pid})")
    run_dir = pathlib.Path(st["run_dir"])
    backup = run_dir / "models.json.backup"
    if backup.exists():
        shutil.copy2(backup, MODELS)
        print("restored ui/public/models.json")
    else:
        MODELS.unlink(missing_ok=True)
        print("removed ui/public/models.json")
    CURRENT.unlink()
    print(f"kept evidence: {run_dir}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"up": up, "doctor": doctor, "down": down}.get(cmd, lambda: sys.exit(__doc__))()
