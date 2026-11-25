# The shared Modal app of the platform-modal adapter (infra/modules/platform-modal). scripts/platforms/modal.py runs
# it with the modal CLI: `modal run modal_app.py::fill` (the weights Volume) and `modal deploy modal_app.py`.
# Exception to the stdlib-only rule of scripts/ (accepted on 2026-11-25): this is Modal code that the modal CLI runs.
# Input: env MODAL_SPEC, the `modal` output of the deployment (JSON). The images keep it in their env, so a container
# imports this file with the same spec. The secrets come from the local env at deploy time, never from this file:
# SERVICE_ACCOUNT_JSON (image pull), HF_TOKEN (Volume fill), SLACK_BOT_TOKEN and SLACK_CHANNEL (the engine posts
# "ready" and "scaled to 0" itself). Details and measurements: docs/research/10-modal-stt-a.md.
import json
import os
import subprocess
import time
import urllib.request

import modal

RAW = os.environ["MODAL_SPEC"]
SPEC = json.loads(RAW)
WEIGHTS = f"/models/{SPEC['weights_dir']}" if SPEC.get("weights_dir") else "/models"


def secret(*keys):
    """A secret from the local env at deploy time. In a container the values are not read again."""
    return modal.Secret.from_dict({k: os.environ.get(k, "") for k in keys})


def big_thread_stack():
    """Modal (gVisor) runs with `ulimit -s unlimited`, so glibc gives each new thread only 2 MB of stack (8 MB on a
    normal Docker host). The STT-A model load runs in a thread and ended in SIGSEGV on most starts; with 64 MB it did
    not (trials 2026-11-25, docs/research/10-modal-stt-a.md). glibc reads the limit when the engine process starts."""
    import resource
    resource.setrlimit(resource.RLIMIT_STACK, (64 << 20, resource.RLIM_INFINITY))


volume = modal.Volume.from_name(SPEC["volume"], create_if_missing=True, version=2)
app = modal.App(SPEC["app"])

engine_image = (
    modal.Image.from_registry(SPEC["image"], secret=secret("SERVICE_ACCOUNT_JSON"))
    .entrypoint([])  # the image ENTRYPOINT starts the server and does not run the args of Modal: Modal starts its own runtime
    # Modal looks for `python` on the PATH; the vLLM base image has only python3.
    .run_commands('command -v python || ln -s "$(command -v python3)" /usr/local/bin/python',
                  'command -v pip || ln -s "$(command -v pip3)" /usr/local/bin/pip')
    # No VLLM_CACHE_ROOT on a Volume: it did not fix the SIGSEGV at some starts and saved only about 15 s.
    .env({**SPEC["env"], "MODAL_SPEC": RAW})
)

fill_image = (
    modal.Image.debian_slim().pip_install("huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "MODAL_SPEC": RAW})
)


@app.function(image=fill_image, volumes={"/models": volume}, secrets=[secret("HF_TOKEN")], timeout=3600)
def fill():
    """Copy hf_repos (folder -> Hugging Face repo) into the Volume. Files that are already there are not copied again."""
    from huggingface_hub import snapshot_download
    for folder, repo in SPEC["hf_repos"].items():
        t = time.time()
        snapshot_download(repo, local_dir=os.path.join(WEIGHTS, folder))
        print(f"{repo} -> {os.path.join(WEIGHTS, folder)}: {time.time() - t:.0f} s", flush=True)
    volume.commit()


@app.cls(image=engine_image, gpu=SPEC["gpus"], cpu=SPEC["cpu"], memory=SPEC["memory_mb"], volumes={"/models": volume},
         secrets=[secret("SLACK_BOT_TOKEN", "SLACK_CHANNEL")], scaledown_window=SPEC["idle_seconds"],
         max_containers=SPEC["max_containers"], timeout=SPEC["timeout"])
class Engine:
    @modal.enter()
    def start(self):
        # The engine opens its port at once and answers 503 while it loads: no request goes in before the health route is 200.
        t = time.time()
        subprocess.run(["nvidia-smi", "-L"], check=False)  # the GPU type in the log (Modal picks from SPEC["gpus"])
        print(f"modal: slack {'on' if os.environ.get('SLACK_BOT_TOKEN') and os.environ.get('SLACK_CHANNEL') else 'off'}", flush=True)
        self.proc = subprocess.Popen(SPEC["command"], cwd=SPEC["workdir"], preexec_fn=big_thread_stack)
        url = f"http://127.0.0.1:{SPEC['port']}{SPEC['health_route']}"
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"engine exited with {self.proc.returncode}")
            try:
                if urllib.request.urlopen(url, timeout=2).status == 200:
                    break
            except OSError:  # connection refused, or HTTP 503 while it loads
                pass
            time.sleep(1)
        print(f"modal: engine ready after {time.time() - t:.1f} s", flush=True)

    @modal.exit()
    def stop(self):
        # SIGTERM to the engine: uvicorn runs its shutdown, so the "scaled to 0" Slack message goes out.
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    @modal.web_server(SPEC["port"], startup_timeout=SPEC["timeout"], requires_proxy_auth=True, label=SPEC["app"])
    def serve(self):
        pass
