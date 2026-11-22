"""The HTTP server over a real socket."""
import http.client
import json
import threading
import unittest

from stt_api import server


class ServerTest(unittest.TestCase):
    def test_negative_content_length_400(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
            conn.putrequest("POST", "/v1beta/uploads")
            conn.putheader("Content-Length", "-1")
            conn.endheaders()
            r = conn.getresponse()
            code, a = r.status, json.loads(r.read())
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(code, 400)
        self.assertIn("negative Content-Length", a["error"]["message"])
