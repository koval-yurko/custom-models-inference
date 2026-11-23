import importlib.util, pathlib, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("verify_ui", HERE / "verify-ui.py")
vu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vu)


class PointToMock(unittest.TestCase):
    def test_point_to_mock(self):
        cfg = {"models": [{"id": "a", "base_url": "http://localhost:5181/vertex",
                           "platforms": [{"id": "vertex", "base_url": "x"}, {"id": "runpod", "base_url": "y"}]},
                          {"id": "b", "base_url": "http://localhost:5181"}]}
        out = vu.point_to_mock(cfg, "http://127.0.0.1:9")
        self.assertEqual([m["base_url"] for m in out["models"]], ["http://127.0.0.1:9", "http://127.0.0.1:9"])
        self.assertEqual([p["base_url"] for p in out["models"][0]["platforms"]], ["http://127.0.0.1:9/vertex", "http://127.0.0.1:9/runpod"])


if __name__ == "__main__":
    unittest.main()
