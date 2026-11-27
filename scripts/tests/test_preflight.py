import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("preflight", pathlib.Path(__file__).resolve().parent.parent / "preflight.py")
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class RunpodLevel(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(preflight.runpod_level(-0.02), "FAIL")
        self.assertEqual(preflight.runpod_level(0.0), "FAIL")
        self.assertEqual(preflight.runpod_level(0.5), "WARN")
        self.assertEqual(preflight.runpod_level(1.0), "ok")


if __name__ == "__main__":
    unittest.main()
