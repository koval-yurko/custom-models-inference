import importlib.util, json, pathlib, unittest

_spec = importlib.util.spec_from_file_location("cors_proxy", pathlib.Path(__file__).parent.parent / "cors_proxy.py")
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)

T = {
    "vertex": {"url": "https://v/x:rawPredict", "append_path": False, "auth": "google"},
    "runpod": {"url": "https://r", "append_path": True, "auth": "runpod"},
}


class Pick(unittest.TestCase):
    def test_prefix_selects_target(self):
        self.assertEqual(cp.pick("/runpod/v1/chat/completions", T, "vertex"), ("runpod", "/v1/chat/completions"))

    def test_old_path_uses_default(self):
        self.assertEqual(cp.pick("/v1/chat/completions", T, "vertex"), ("vertex", "/v1/chat/completions"))

    def test_bare_prefix(self):
        self.assertEqual(cp.pick("/runpod", T, "vertex"), ("runpod", "/"))

    def test_similar_segment_is_not_a_prefix(self):
        self.assertEqual(cp.pick("/runpodx/v1", T, "vertex"), ("vertex", "/runpodx/v1"))

    def test_query_string_kept(self):
        pid, rest = cp.pick("/runpod/v1/x?a=1", T, "vertex")
        self.assertEqual((pid, rest), ("runpod", "/v1/x?a=1"))
        self.assertEqual(cp.upstream_url(T["runpod"], rest), "https://r/v1/x?a=1")


class Upstream(unittest.TestCase):
    def test_fixed_url_ignores_rest(self):
        self.assertEqual(cp.upstream_url(T["vertex"], "/v1/chat/completions"), "https://v/x:rawPredict")


class Auth(unittest.TestCase):
    def test_google_auth_uses_token(self):
        self.assertEqual(cp.auth_header("google", {}, lambda: "tok"), "Bearer tok")

    def test_key_auth_reads_env(self):
        self.assertEqual(cp.auth_header("runpod", {"RUNPOD_API_KEY": "k"}, None), "Bearer k")

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            cp.auth_header("runpod", {}, None)


class Handler(unittest.TestCase):
    def test_missing_key_gives_502_with_cors(self):
        import http.client, threading
        from http.server import ThreadingHTTPServer
        cp.TARGETS, cp.DEFAULT, cp.TIMEOUT = T, "vertex", 5
        srv = ThreadingHTTPServer(("127.0.0.1", 0), cp.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
            c.request("POST", "/runpod/v1/chat/completions", b"{}", {"Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual(r.status, 502)
            self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "*")
            self.assertIn(b"RUNPOD_API_KEY", r.read())
        finally:
            srv.shutdown()


class Headers(unittest.TestCase):
    def test_post_always_sends_json(self):
        # As before the multi-target change: a client without a JSON Content-Type still reaches the model as JSON.
        self.assertEqual(cp.upstream_headers("POST", "Bearer k"), {"Authorization": "Bearer k", "Content-Type": "application/json"})

    def test_get_has_no_content_type(self):
        self.assertEqual(cp.upstream_headers("GET", "Bearer k"), {"Authorization": "Bearer k"})


class Load(unittest.TestCase):
    def test_load_targets_rejects_unknown_default(self):
        with self.assertRaises(ValueError):
            cp.load_targets({"TARGETS": json.dumps(T), "DEFAULT": "x"})

    def test_load_targets(self):
        self.assertEqual(cp.load_targets({"TARGETS": json.dumps(T), "DEFAULT": "vertex"}), (T, "vertex"))


if __name__ == "__main__":
    unittest.main()
