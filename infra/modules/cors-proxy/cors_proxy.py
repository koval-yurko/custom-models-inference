# Runs in the stock python image (python3 -u -c <this file>). Not a package: stdlib only, no build step.
# The gateway calls this service. It adds CORS headers to every answer (also the 429 and 5xx of the platforms,
# which come without them) and forwards GET and POST to the target of the platform with its credential.
# TARGETS (JSON) maps a platform id to {url, append_path, auth}. The first path segment picks the target
# (/vertex/v1/x -> vertex, path /v1/x). Any other path goes to DEFAULT with the full path (the old paths).
import http.client, json, os, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-api-key, authorization",
    "Access-Control-Max-Age": "600",
}
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_tok = {"value": "", "exp": 0.0}
KEYS = {"runpod": "RUNPOD_API_KEY"}  # auth -> env var (a Secret Manager secret)


def load_targets(environ):
    targets, default = json.loads(environ["TARGETS"]), environ["DEFAULT"]
    if default not in targets:
        raise ValueError(f"DEFAULT {default!r} is not in TARGETS {sorted(targets)}")
    return targets, default


def pick(path, targets, default):
    """Return (platform id, path for the upstream). The query string stays on the path."""
    head, sep, tail = path[1:].partition("/")
    seg, q, query = head.partition("?")
    if seg in targets:
        return seg, ("/" + tail) if sep else ("/" + q + query if q else "/")
    return default, path


def upstream_headers(method, authorization):
    # A POST always goes upstream as JSON, also when the client sent no or another Content-Type (as before).
    return {"Authorization": authorization, **({"Content-Type": "application/json"} if method == "POST" else {})}


def upstream_url(target, rest):
    # append_path: the target is a base URL (Vertex AI :invoke, Runpod). Else one fixed URL (:rawPredict).
    return target["url"] + rest if target["append_path"] else target["url"]


def token():
    if time.time() > _tok["exp"] - 60:
        r = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
        d = json.load(urllib.request.urlopen(r, timeout=5))
        _tok.update(value=d["access_token"], exp=time.time() + d["expires_in"])
    return _tok["value"]


def auth_header(auth, environ, google_token):
    """google: the metadata server token. Else the API key of the platform. A missing key raises KeyError (502)."""
    return f"Bearer {google_token()}" if auth == "google" else f"Bearer {environ[KEYS[auth]]}"


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

    def forward(self, method):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method == "POST" else None
        try:
            pid, rest = pick(self.path, TARGETS, DEFAULT)
            t = TARGETS[pid]
            u = urlsplit(upstream_url(t, rest))
            headers = upstream_headers(method, auth_header(t["auth"], os.environ, token))
            conn = http.client.HTTPSConnection(u.netloc, timeout=TIMEOUT)
            conn.request(method, u.path + ("?" + u.query if u.query else ""), body, headers)
            r = conn.getresponse()
        except Exception as e:  # the gateway must always get an answer with CORS headers
            msg = json.dumps({"error": f"proxy: {e}"}).encode()
            return self.reply(502, {"Content-Type": "application/json"}, [msg])
        keep = {k: v for k, v in r.getheaders() if k.lower() in ("content-type", "retry-after")}
        self.reply(r.status, keep, iter(lambda: r.read1(8192), b""))
        conn.close()

    def do_GET(self):
        self.forward("GET")

    def do_POST(self):
        self.forward("POST")


if __name__ == "__main__":
    TARGETS, DEFAULT = load_targets(os.environ)
    TIMEOUT = int(os.environ.get("TIMEOUT", "300"))
    ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
