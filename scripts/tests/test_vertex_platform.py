import pathlib, sys, unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from platforms import vertex  # noqa: E402


class FakeCtx(vertex._Ctx):
    def __init__(self):
        self.d, self.api, self.token, self.v = pathlib.Path("/x"), "https://api", "t", {}


class Call(unittest.TestCase):
    def test_call_has_timeout(self):
        with mock.patch.object(vertex.urllib.request, "urlopen") as u:
            u.return_value.__enter__.return_value.read.return_value = b"{}"
            with mock.patch.object(vertex.json, "load", return_value={}):
                FakeCtx().call("GET", "p")
        self.assertGreater(u.call_args.kwargs.get("timeout") or 0, 0)


class Hint(unittest.TestCase):
    def test_already_deployed_names_both_scripts(self):
        with mock.patch.object(vertex, "_Ctx") as C:
            C.return_value.deployed_ids.return_value = ["1"]
            with self.assertRaises(SystemExit) as e:
                vertex.deploy(vertex.ROOT / "deployments" / "llm-b")
        msg = str(e.exception)
        self.assertIn("./scripts/deploy.py undeploy deployments/llm-b --platform vertex", msg)
        self.assertIn("./scripts/vertex.py undeploy deployments/llm-b", msg)


if __name__ == "__main__":
    unittest.main()
