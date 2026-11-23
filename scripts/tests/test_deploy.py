import importlib.util, pathlib, unittest

HERE = pathlib.Path(__file__).resolve().parent.parent


def load(file, name):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deploy = load("deploy.py", "deploy_script")
streaming = load("gateway-streaming.py", "gateway_streaming")

V = {"id": "vertex", "post_apply": "vertex"}
R = {"id": "runpod", "post_apply": None}
T = {"runpod": R, "vertex": V}


class Select(unittest.TestCase):
    def test_select_all_in_order(self):
        self.assertEqual(deploy.select(["vertex", "runpod"], T, None), [V, R])

    def test_select_one(self):
        self.assertEqual(deploy.select(["vertex", "runpod"], T, "runpod"), [R])

    def test_select_unknown_exits(self):
        with self.assertRaises(SystemExit) as e:
            deploy.select(["vertex"], {"vertex": V}, "azure")
        self.assertEqual(str(e.exception), "unknown platform azure; this model has: vertex")


class GatewayAddress(unittest.TestCase):
    def test_gateway_address_from_output(self):
        a = "module.model.module.gateway.google_api_gateway_gateway.this"
        self.assertEqual(streaming.gateway_address({"gateway_address": {"value": a}}), a)

    def test_gateway_address_fallback(self):
        self.assertEqual(streaming.gateway_address({"gateway_id": {"value": "x"}}), "google_api_gateway_gateway.this")


if __name__ == "__main__":
    unittest.main()
