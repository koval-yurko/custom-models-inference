import importlib.util, os, pathlib, unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent
ENV = {"TF_CLOUD_ORGANIZATION": "o", "TF_CLOUD_PROJECT": "p", "TF_TOKEN_app_terraform_io": "t", "RUNPOD_API_KEY": "k"}


def load():
    spec = importlib.util.spec_from_file_location("hcp_sync", HERE / "hcp-sync.py")
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.dict(os.environ, ENV):
        spec.loader.exec_module(mod)
    return mod


class ProviderKeys(unittest.TestCase):
    def setUp(self):
        self.sync = load()

    def test_runpod_key_goes_to_every_workspace_as_env(self):
        self.assertEqual(self.sync.PROVIDER_KEYS, {"RUNPOD_API_KEY": "k"})

    def test_keys_are_sensitive(self):
        self.assertLessEqual({"RUNPOD_API_KEY", "runpod_api_key"}, self.sync.SENSITIVE)

    def test_core_gets_the_terraform_variable(self):
        self.assertEqual(self.sync.WORKSPACES["custom-models-bootstrap"][1]["runpod_api_key"], "k")


class ModalWorkspace(unittest.TestCase):
    def test_only_folders_that_declare_the_variable_get_it(self):
        with mock.patch.dict(os.environ, {"MODAL_PROFILE": "ws"}):
            sync = load()
        got = {d for d, v in sync.WORKSPACES.values() if v.get("modal_workspace") == "ws"}
        self.assertIn("deployments/stt-a-qwen3-asr-diar", got)
        self.assertNotIn("infra/core", got)
        self.assertNotIn("modal_workspace", sync.COMMON)  # the shared dict stays unchanged


class RunpodSecrets(unittest.TestCase):
    def setUp(self):
        self.sync = load()
        self.calls = []

    def call(self, method, path="", body=None):
        self.calls.append((method, path, body))
        return {"secrets": [{"name": "slack_channel", "id": "s1"}, {"name": "other", "id": "s2"}]} if method == "GET" else {}

    def run_sync(self, dry=False, secrets=None):
        with mock.patch.object(self.sync, "DRY", dry), \
                mock.patch.object(self.sync, "RUNPOD_SECRETS", secrets or {"slack_bot_token": "xoxb", "slack_channel": "#m"}), \
                mock.patch.dict(os.environ, {"RUNPOD_API_KEY": "k"}):
            self.sync.sync_runpod_secrets(self.call)

    def test_creates_missing_and_updates_existing(self):
        self.run_sync()
        self.assertEqual(self.calls[1:], [("POST", "", {"name": "slack_bot_token", "value": "xoxb"}),
                                          ("PATCH", "/s1", {"value": "#m"})])

    def test_dry_run_only_reads(self):
        self.run_sync(dry=True)
        self.assertEqual([c[0] for c in self.calls], ["GET"])

    def test_empty_value_is_skipped(self):
        self.run_sync(secrets={"slack_bot_token": None, "slack_channel": "#m"})
        self.assertEqual(self.calls[1:], [("PATCH", "/s1", {"value": "#m"})])


if __name__ == "__main__":
    unittest.main()
