import importlib.util, pathlib, unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent.parent


def load(file, name):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ui = load("ui-deploy.py", "ui_deploy")

E = {"id": "a", "base_url": "https://gw/vertex", "platforms": [
    {"id": "vertex", "base_url": "https://gw/vertex"}, {"id": "runpod", "base_url": "https://gw/runpod"}]}


class KeepDeployed(unittest.TestCase):
    def test_all_deployed(self):
        self.assertEqual(ui.keep_deployed(E, {"vertex": True, "runpod": True}), E)

    def test_default_gone_moves_base_url(self):
        out = ui.keep_deployed(E, {"vertex": False, "runpod": True})
        self.assertEqual((out["base_url"], [p["id"] for p in out["platforms"]]), ("https://gw/runpod", ["runpod"]))
        self.assertEqual(len(E["platforms"]), 2)  # input unchanged

    def test_none_left(self):
        self.assertIsNone(ui.keep_deployed(E, {"vertex": False, "runpod": False}))

    def test_old_entry_unchanged(self):
        old = {"id": "b", "base_url": "https://gw"}
        self.assertIs(ui.keep_deployed(old, {}), old)


class PlatformDeployed(unittest.TestCase):
    T = {"vertex": {"id": "vertex", "post_apply": "vertex"}, "runpod": {"id": "runpod", "post_apply": None}}

    def step_with(self, deployed):
        vertex = mock.Mock(deployed=deployed)
        return lambda t: vertex if t["post_apply"] else None

    def test_no_post_apply_is_deployed_and_a_failed_check_keeps_it(self):
        with mock.patch.object(ui.deploy, "step", self.step_with(mock.Mock(side_effect=SystemExit("no token")))):
            self.assertEqual(ui.platform_deployed(pathlib.Path("d"), self.T), {"vertex": True, "runpod": True})

    def test_not_deployed(self):
        with mock.patch.object(ui.deploy, "step", self.step_with(mock.Mock(return_value=False))):
            self.assertEqual(ui.platform_deployed(pathlib.Path("d"), {"vertex": self.T["vertex"]}), {"vertex": False})


class StatusRow(unittest.TestCase):
    M = {"id": "a", "title": "A", "type": "llm", "platforms": [{"id": "vertex"}]}

    def test_states(self):
        st = {"version": "img:1", "platforms": [{"id": "vertex", "serve": True}, {"id": "runpod", "serve": False}, {"id": "modal", "serve": True}, {"id": "x", "serve": True, "parked": True}]}
        row = ui.status_row(self.M, st, {"vertex": False}, False)
        self.assertEqual(row["version"], "img:1")
        self.assertFalse(row["tab"])
        self.assertEqual(row["platforms"], [{"id": "vertex", "state": "not deployed"}, {"id": "runpod", "state": "off"}, {"id": "modal", "state": "serving"}, {"id": "x", "state": "parked"}])

    def test_without_status_uses_the_ui_platforms(self):
        row = ui.status_row(self.M, None, {}, True)
        self.assertEqual((row["version"], row["platforms"]), ("", [{"id": "vertex", "state": "serving"}]))


if __name__ == "__main__":
    unittest.main()
