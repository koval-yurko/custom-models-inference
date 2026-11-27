"""Health routes and bind address of app.py, with vLLM stubbed out (no GPU, no vllm package).
Run from image/: uv run --with fastapi --with httpx --with uvicorn python -m unittest tests.test_main"""
import os
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parent.parent / "app.py"

# Stub the vllm modules that app.py imports.
for mod in ("vllm", "vllm.sampling_params", "vllm.v1", "vllm.v1.engine", "vllm.v1.engine.async_llm"):
    sys.modules.setdefault(mod, types.ModuleType(mod))
sys.modules["vllm"].AsyncEngineArgs = lambda **kw: kw
sys.modules["vllm"].SamplingParams = object
sys.modules["vllm.sampling_params"].StructuredOutputsParams = object
sys.modules["vllm.v1.engine.async_llm"].AsyncLLM = object
os.environ.setdefault("MODEL", "/tmp/model")
sys.path.insert(0, str(APP.parent))
import app  # noqa: E402


class Engine:
    async def check_health(self):
        pass


class Health(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)  # no "with": the lifespan (engine load) does not run
        self.addCleanup(setattr, app, "engine", None)

    def test_runpod_loading_is_204_on_ping_and_health(self):
        with mock.patch.dict(os.environ, {"SETUP_PLATFORM": "runpod"}):
            for path in ("/ping", "/health"):
                self.assertEqual(self.client.get(path).status_code, 204, path)

    def test_vertex_loading_is_503(self):
        with mock.patch.dict(os.environ, {"SETUP_PLATFORM": ""}):
            self.assertEqual(self.client.get("/ping").status_code, 503)

    def test_ready_is_200_on_ping_and_health(self):
        app.engine = Engine()
        for path in ("/ping", "/health"):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class Bind(unittest.TestCase):
    def test_listens_on_ipv4_all(self):
        # The Runpod probe comes over IPv4: "::" would be IPv6 only.
        with mock.patch("uvicorn.run") as run, mock.patch.dict(os.environ, {"PORT": "9000"}):
            runpy.run_path(str(APP), run_name="__main__")
        self.assertEqual(run.call_args.kwargs["host"], "0.0.0.0")
        self.assertEqual(run.call_args.kwargs["port"], 9000)


if __name__ == "__main__":
    unittest.main()
