import json, pathlib, sys, types, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from platforms import modal  # noqa: E402

S = {"app": "stt-a", "hf_repos": {"asr": "Qwen/Qwen3-ASR-1.7B"}}


def ok(stdout=""):
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


class Deploy(unittest.TestCase):
    def run_deploy(self, s):
        with mock.patch.object(modal, "spec", return_value=s), \
                mock.patch.object(modal, "tf_output", return_value="{key}") as out, \
                mock.patch.object(modal, "cli", return_value=ok()) as cli:
            modal.deploy(pathlib.Path("/d"))
        return out, cli

    def test_fill_then_deploy_with_spec_and_pull_key(self):
        out, cli = self.run_deploy(S)
        self.assertEqual(out.call_args.args, (modal.ROOT / "infra" / "core", "-raw", "registry_pull_key"))
        (fill, env1), (dep, env2) = [c.args for c in cli.call_args_list]
        self.assertEqual((fill, dep), (["run", f"{modal.APP}::fill"], ["deploy", str(modal.APP)]))
        self.assertEqual(json.loads(env2["MODAL_SPEC"]), S)
        self.assertEqual(env2["SERVICE_ACCOUNT_JSON"], "{key}")

    def test_no_fill_without_hf_repos(self):
        _, cli = self.run_deploy({**S, "hf_repos": {}})
        self.assertEqual([c.args[0][0] for c in cli.call_args_list], ["deploy"])

    def test_cli_is_pinned(self):
        self.assertEqual(modal.MODAL[:3], ["uvx", "--from", "modal==1.6.4"])


class State(unittest.TestCase):
    APPS = [{"description": "stt-a", "state": "stopped"}, {"description": "other", "state": "deployed"}]

    def test_is_deployed(self):
        self.assertFalse(modal.is_deployed(self.APPS, "stt-a"))
        self.assertTrue(modal.is_deployed(self.APPS + [{"description": "stt-a", "state": "deployed"}], "stt-a"))

    def test_undeploy_skips_a_stopped_app(self):
        with mock.patch.object(modal, "spec", return_value=S), \
                mock.patch.object(modal, "cli", return_value=ok(json.dumps(self.APPS))) as cli:
            modal.undeploy(pathlib.Path("/d"))
        self.assertEqual([c.args[0] for c in cli.call_args_list], [["app", "list", "--json"]])

    def test_undeploy_stops_a_deployed_app(self):
        apps = [{"description": "stt-a", "state": "deployed"}]
        with mock.patch.object(modal, "spec", return_value=S), \
                mock.patch.object(modal, "cli", return_value=ok(json.dumps(apps))) as cli:
            modal.undeploy(pathlib.Path("/d"))
        self.assertEqual(cli.call_args_list[-1].args[0], ["app", "stop", "stt-a", "--yes"])


if __name__ == "__main__":
    unittest.main()
