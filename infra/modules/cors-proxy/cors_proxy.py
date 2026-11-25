# Runs in the stock python image (python3 -u -c <this file>). Not a package: stdlib only, no build step.
# The gateway calls this service. It adds CORS headers to every answer (also the 429 and 5xx of the platforms,
# which come without them) and forwards GET and POST to the target of the platform with its credential.
# TARGETS (JSON) maps a platform id to {url, append_path, auth}. The first path segment picks the target
# (/vertex/v1/x -> vertex, path /v1/x). Any other path goes to DEFAULT with the full path (the old paths).
# A Runpod answer "no workers available" becomes 429 with Retry-After: 30 (cold_answer), so the UI retries.
# Runpod holds a request at 0 workers until a worker is up, longer than the 300 s gateway deadline for a slow
# cold start. So a non-google target that sends no answer headers in COLD_WAIT seconds also gets 429 (wait_answer).
# Modal stops a web request after 150 s with a 303 to a result URL (a cold start takes about 160 s): the proxy follows
# it with a GET (redirect), and the time of all hops counts against COLD_WAIT.
import http.client, json, os, sys, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlsplit

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-api-key, authorization",
    "Access-Control-Max-Age": "600",
}
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_tok = {"value": "", "exp": 0.0}
KEYS = {"runpod": "RUNPOD_API_KEY", "modal": "MODAL_API_KEY"}  # auth -> env var (a Secret Manager secret)
MAX_HOPS = 10  # Modal allows 20 redirects; 10 x 150 s is far above COLD_WAIT
_ok = {}  # platform id -> time of its last answer below 500 (in this instance)


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


def redirect(auth, status, headers, url):
    """The absolute URL of a Modal 303 (or 302) to follow, else None. Only Modal: other platforms keep their answer."""
    loc = next((v for k, v in headers if k.lower() == "location"), None)
    return urljoin(url, loc) if auth == "modal" and status in (302, 303) and loc else None


def path_of(u):
    return u.path + ("?" + u.query if u.query else "")


def cold_answer(auth, status, body):
    """True: the platform has no worker yet, so the proxy answers 429 (the UI retries every 30 s).
    The Runpod status and body are a guess until the first cold call (spec Open points): change only this function."""
    return auth == "runpod" and 400 <= status < 600 and b"no worker" in body.lower()  # "no worker(s) available"


def wait_answer(pid, last_ok, now, cold_wait, warm_seconds):
    """(status, message) when a non-google target sent no answer headers in cold_wait seconds.
    It answered within warm_seconds (its idle timeout): a worker is up and the request is only slow, so 504.
    A retry would run the same long request again. Else the worker is starting: 429, so the client retries.
    shortcut: _ok is per proxy instance; a new instance treats a warm worker as cold (1 extra retry at most)."""
    if now - last_ok < warm_seconds:
        return 504, f"proxy: {pid} sent no answer in {cold_wait} s"
    return 429, f"proxy: {pid} is starting, retry in 30 s"


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
            url = upstream_url(t, rest)
            u = urlsplit(url)
            headers = upstream_headers(method, auth_header(t["auth"], os.environ, token))
            cold = t["auth"] != "google"
            conn = http.client.HTTPSConnection(u.netloc, timeout=COLD_WAIT if cold else TIMEOUT)
            start = time.time()
            try:
                conn.request(method, path_of(u), body, headers)
                r = conn.getresponse()
                for _ in range(MAX_HOPS):
                    url = redirect(t["auth"], r.status, r.getheaders(), url)
                    if not url:
                        break
                    r.read()
                    conn.close()
                    left = COLD_WAIT - (time.time() - start)
                    if left <= 0:
                        raise TimeoutError("no answer in COLD_WAIT")
                    u = urlsplit(url)
                    conn = http.client.HTTPSConnection(u.netloc, timeout=left)
                    conn.request("GET", path_of(u), None, {"Authorization": headers["Authorization"]})
                    r = conn.getresponse()
            except TimeoutError:
                if not cold:
                    raise
                conn.close()
                code, msg = wait_answer(pid, _ok.get(pid, 0.0), time.time(), COLD_WAIT, WARM_SECONDS)
                print(f"{pid} wait: {code} after {COLD_WAIT} s", file=sys.stderr)
                return self.reply(code, {"Content-Type": "application/json", **({"Retry-After": "30"} if code == 429 else {})},
                                  [json.dumps({"error": msg}).encode()])
            if cold and getattr(conn, "sock", None):  # the answer started: the body may take up to TIMEOUT
                conn.sock.settimeout(TIMEOUT)
        except Exception as e:  # the gateway must always get an answer with CORS headers
            msg = json.dumps({"error": f"proxy: {e}"}).encode()
            return self.reply(502, {"Content-Type": "application/json"}, [msg])
        keep = {k: v for k, v in r.getheaders() if k.lower() in ("content-type", "retry-after")}
        if r.status < 500:
            _ok[pid] = time.time()
        if t["auth"] != "google" and r.status >= 400:  # an error body is small: read it to check for a cold start
            body = r.read()
            conn.close()
            if cold_answer(t["auth"], r.status, body):
                print(f"{t['auth']} cold: {r.status} {body[:200]!r}", file=sys.stderr)
                keep = {k: v for k, v in keep.items() if k.lower() != "retry-after"}
                return self.reply(429, {**keep, "Retry-After": "30"}, [body])
            return self.reply(r.status, keep, [body] if body else [])
        self.reply(r.status, keep, iter(lambda: r.read1(8192), b""))  # stream good answers (SSE)
        conn.close()

    def do_GET(self):
        self.forward("GET")

    def do_POST(self):
        self.forward("POST")


if __name__ == "__main__":
    TARGETS, DEFAULT = load_targets(os.environ)
    TIMEOUT = int(os.environ.get("TIMEOUT", "300"))
    COLD_WAIT = int(os.environ.get("COLD_WAIT", "280"))  # below the 300 s gateway deadline
    WARM_SECONDS = int(os.environ.get("WARM_SECONDS", "300"))  # the idle timeout of the platform
    ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
