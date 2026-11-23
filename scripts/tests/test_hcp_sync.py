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


if __name__ == "__main__":
    unittest.main()
