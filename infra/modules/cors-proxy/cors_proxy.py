# Runs in the stock python image (python3 -u -c <this file>). Not a package: stdlib only, no build step.
# The gateway calls this service. It adds CORS headers to every answer (also the 429 and 5xx of Vertex AI,
# which come without them) and forwards the POST body to Vertex AI rawPredict with its own access token.
import http.client, json, os, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TARGET = urlsplit(os.environ["TARGET"])
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-api-key, authorization",
    "Access-Control-Max-Age": "600",
}
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_tok = {"value": "", "exp": 0.0}


def token():
    if time.time() > _tok["exp"] - 60:
        r = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
        d = json.load(urllib.request.urlopen(r, timeout=5))
        _tok.update(value=d["access_token"], exp=time.time() + d["expires_in"])
    return _tok["value"]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, code, headers, chunks=()):
        self.send_response(code)
        for k, v in {**headers, **CORS}.items():
            self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for c in chunks:
            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")

    def do_OPTIONS(self):
        # A 204 has no body: chunked encoding is a protocol error for the gateway (502).
        self.send_response(204)
        for k, v in CORS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            conn = http.client.HTTPSConnection(TARGET.netloc, timeout=300)
            conn.request("POST", TARGET.path, body, {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
            r = conn.getresponse()
        except Exception as e:  # the gateway must always get an answer with CORS headers
            msg = json.dumps({"error": f"proxy: {e}"}).encode()
            return self.reply(502, {"Content-Type": "application/json"}, [msg])
        keep = {k: v for k, v in r.getheaders() if k.lower() in ("content-type", "retry-after")}
        self.reply(r.status, keep, iter(lambda: r.read1(8192), b""))
        conn.close()


ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
