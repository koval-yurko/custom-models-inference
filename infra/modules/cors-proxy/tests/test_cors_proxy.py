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


class ColdAnswer(unittest.TestCase):
    def test_runpod_no_workers_is_cold(self):
        self.assertTrue(cp.cold_answer("runpod", 503, b'{"error":"No workers available"}'))

    def test_runpod_no_workers_on_400_is_cold(self):
        self.assertTrue(cp.cold_answer("runpod", 400, b"no workers available"))

    def test_runpod_singular_no_worker_is_cold(self):
        self.assertTrue(cp.cold_answer("runpod", 503, b'{"error":"No worker available"}'))

    def test_runpod_other_error_is_not_cold(self):
        self.assertFalse(cp.cold_answer("runpod", 500, b'{"error":"CUDA out of memory"}'))

    def test_good_answer_is_never_cold(self):
        self.assertFalse(cp.cold_answer("runpod", 200, b"no workers"))

    def test_vertex_is_not_mapped(self):
        self.assertFalse(cp.cold_answer("google", 503, b"no workers available"))


class Handler(unittest.TestCase):
    def test_missing_key_gives_502_with_cors(self):
        import http.client, threading
        from http.server import ThreadingHTTPServer
        cp.TARGETS, cp.DEFAULT, cp.TIMEOUT, cp.COLD_WAIT, cp.WARM_SECONDS = T, "vertex", 5, 1, 300
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


class FakeUpstream:
    """Stands in for http.client.HTTPSConnection: answers with a fixed status, headers and body.
    answer = None: no answer headers in time (getresponse raises TimeoutError, as a socket timeout does)."""
    answer = (200, [("Content-Type", "text/event-stream")], b"data: 1\n\n")

    def __init__(self, *a, **k):
        pass

    def request(self, *a, **k):
        pass

    def getresponse(self):
        import io
        if self.answer is None:
            raise TimeoutError("timed out")
        status, headers, body = self.answer
        r = io.BufferedReader(io.BytesIO(body))
        r.status, r.getheaders = status, lambda: headers
        return r

    def close(self):
        pass


class Mapping(unittest.TestCase):
    def call(self, answer):
        import http.client, os, threading
        from http.server import ThreadingHTTPServer
        from unittest import mock
        cp.TARGETS, cp.DEFAULT, cp.TIMEOUT, cp.COLD_WAIT, cp.WARM_SECONDS = T, "vertex", 5, 1, 300
        FakeUpstream.answer = answer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), cp.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(cp.http.client, "HTTPSConnection", FakeUpstream), mock.patch.dict(os.environ, {"RUNPOD_API_KEY": "k"}):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
                c.request("POST", "/runpod/v1/chat/completions", b"{}", {"Content-Type": "application/json"})
                r = c.getresponse()
                return r.status, r.getheader("Retry-After"), r.getheader("Access-Control-Allow-Origin"), r.read()
        finally:
            srv.shutdown()

    def test_no_workers_becomes_429_with_cors(self):
        status, retry, cors, body = self.call((503, [("Content-Type", "application/json"), ("retry-after", "5")], b'{"error":"no workers available"}'))
        self.assertEqual((status, retry, cors), (429, "30", "*"))
        self.assertIn(b"no workers", body)

    def test_other_error_keeps_status_and_body(self):
        status, retry, _, body = self.call((500, [("Content-Type", "application/json")], b'{"error":"boom"}'))
        self.assertEqual((status, retry, body), (500, None, b'{"error":"boom"}'))

    def test_no_answer_in_cold_wait_becomes_429(self):
        cp._ok.clear()
        status, retry, cors, body = self.call(None)
        self.assertEqual((status, retry, cors), (429, "30", "*"))
        self.assertIn(b"is starting", body)

    def test_no_answer_after_a_recent_answer_is_504(self):
        import time
        cp._ok["runpod"] = time.time()  # a worker answered just now: the request is slow, a retry would repeat it
        status, retry, cors, _ = self.call(None)
        self.assertEqual((status, retry, cors), (504, None, "*"))

    def test_good_answer_marks_the_target_warm(self):
        cp._ok.clear()
        self.call((200, [("Content-Type", "application/json")], b"{}"))
        self.assertIn("runpod", cp._ok)

    def test_wait_answer(self):
        self.assertEqual(cp.wait_answer("runpod", 0.0, 1000.0, 280, 300)[0], 429)
        self.assertEqual(cp.wait_answer("runpod", 800.0, 1000.0, 280, 300)[0], 504)

    def test_good_answer_streams_through(self):
        status, _, cors, body = self.call((200, [("Content-Type", "text/event-stream")], b"data: 1\n\ndata: 2\n\n"))
        self.assertEqual((status, cors, body), (200, "*", b"data: 1\n\ndata: 2\n\n"))


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
