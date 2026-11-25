"""HTTP server of the STT API service: CORS headers, JSON body in and out. All route logic is in routes.py."""
import json
import os
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stt_api.gcp import GcsStore, gpu_post, sign_blob
from stt_api.routes import error, route

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, x-api-key, authorization",
    "Access-Control-Max-Age": "600",
}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    store = cfg = None  # set in __main__

    def reply(self, code, obj=None):
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        for k, v in CORS.items():
            self.send_header(k, v)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.reply(204)

    def handle_call(self, method):
        try:
            size = int(self.headers.get("Content-Length") or 0)
            if size < 0:  # read(-1) waits for the end of the stream
                raise ValueError("negative Content-Length")
            raw = self.rfile.read(size)
            body = json.loads(raw) if raw else None
        except ValueError as e:  # bad Content-Length or bad JSON
            return self.reply(400, error(f"bad request body: {e}"))
        try:
            code, obj = route(method, self.path, body, self.store, gpu_post, self.cfg,
                              lambda: datetime.now(timezone.utc))
        except Exception:  # the gateway must always get an answer with CORS headers; details go to the log only
            traceback.print_exc()
            code, obj = 500, error("internal error", 500)
        self.reply(code, obj)

    def do_GET(self):
        self.handle_call("GET")

    def do_POST(self):
        self.handle_call("POST")

    def do_PUT(self):
        self.handle_call("PUT")

    def do_DELETE(self):
        self.handle_call("DELETE")


def main():
    H.store = GcsStore(os.environ["AUDIO_BUCKET"])
    H.cfg = {"bucket": os.environ["AUDIO_BUCKET"], "sa_email": os.environ["SA_EMAIL"],
             # TARGET: the CORS proxy URL. PLATFORMS: platform ids, the default first (stt_api.tf sets both).
             "image_tag": os.environ.get("IMAGE_TAG", ""), "target": os.environ["TARGET"].rstrip("/"),
             "platforms": os.environ["PLATFORMS"].split(","),
             "sign": sign_blob(os.environ["SA_EMAIL"])}
    ThreadingHTTPServer(("", int(os.environ.get("PORT", "8080"))), H).serve_forever()
