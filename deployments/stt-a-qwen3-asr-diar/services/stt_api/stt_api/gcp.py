"""Google Cloud calls: the GCS store, V4 signed URLs, the GPU call (through the CORS proxy) and the tokens.
The service signs through the IAM Credentials signBlob API with its own service account, so it needs no key file."""
import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

EXPIRES = 900  # signed URLs last 15 minutes
GPU_TIMEOUT = 900  # the Vertex AI endpoint stops a request at 600 s (spec fact 10)
HOST = "storage.googleapis.com"
META = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
IDENTITY = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
_tok = {"value": "", "exp": 0.0}
_ids = {}  # audience -> (ID token, expiry)


def signed_put(bucket, name, mime, size, sa_email, now, sign):
    return _signed("PUT", bucket, name, {"content-type": mime, "host": HOST, "x-goog-content-length-range": f"0,{size}"},
                   sa_email, now, sign)


def signed_get(bucket, name, sa_email, now, sign):
    return _signed("GET", bucket, name, {"host": HOST}, sa_email, now, sign)


def _signed(method, bucket, name, headers, sa_email, now, sign):
    """GCS V4 signing: canonical request -> string to sign -> hex of the RSA signature. headers: lower-case names."""
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    signed = ";".join(sorted(headers))
    scope = f"{day}/auto/storage/goog4_request"
    query = "&".join(f"{k}={quote(v, safe='-_.~')}" for k, v in sorted({
        "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
        "X-Goog-Credential": f"{sa_email}/{scope}",
        "X-Goog-Date": stamp,
        "X-Goog-Expires": str(EXPIRES),
        "X-Goog-SignedHeaders": signed,
    }.items()))
    path = f"/{bucket}/{quote(name, safe='/-_.~')}"
    canonical = "\n".join([method, path, query, *(f"{k}:{headers[k]}" for k in sorted(headers)), "", signed,
                           "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["GOOG4-RSA-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    return f"https://{HOST}{path}?{query}&X-Goog-Signature={sign(to_sign.encode()).hex()}"


def token():
    if time.time() > _tok["exp"] - 60:
        r = urllib.request.Request(META, headers={"Metadata-Flavor": "Google"})
        d = json.load(urllib.request.urlopen(r, timeout=5))
        _tok.update(value=d["access_token"], exp=time.time() + d["expires_in"])
    return _tok["value"]


def _auth(extra=None):
    return {"Authorization": f"Bearer {token()}", **(extra or {})}


class GcsStore:
    """GCS JSON API. write never replaces an object (ifGenerationMatch=0), unless replace=True (only *.names.json and
    reference.json). delete removes 1 object (the delete routes of the UI; the IAM grant is in stt_api.tf)."""

    def __init__(self, bucket):
        self.api = f"https://{HOST}/storage/v1/b/{bucket}/o"
        self.upload = f"https://{HOST}/upload/storage/v1/b/{bucket}/o"

    def list(self, prefix):
        items, page = [], None
        while True:
            q = {"prefix": prefix, **({"pageToken": page} if page else {})}
            d = json.load(urllib.request.urlopen(urllib.request.Request(f"{self.api}?{urlencode(q)}", headers=_auth()),
                                                 timeout=30))
            items += d.get("items", [])
            page = d.get("nextPageToken")
            if not page:
                return items

    def read(self, name):
        try:
            r = urllib.request.Request(f"{self.api}/{quote(name, safe='')}?alt=media", headers=_auth())
            return urllib.request.urlopen(r, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise KeyError(name) from e
            raise

    def delete(self, name):
        """Delete 1 object. A missing object is not an error (a repeated delete)."""
        try:
            r = urllib.request.Request(f"{self.api}/{quote(name, safe='')}", headers=_auth(), method="DELETE")
            urllib.request.urlopen(r, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    def write(self, name, data, content_type, metadata=None, replace=False):
        b = "stt-files-boundary"
        head = json.dumps({"name": name, "contentType": content_type, "metadata": metadata or {}})
        body = (f"--{b}\r\nContent-Type: application/json\r\n\r\n{head}\r\n--{b}\r\n"
                f"Content-Type: {content_type}\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        q = "uploadType=multipart" + ("" if replace else "&ifGenerationMatch=0")
        r = urllib.request.Request(f"{self.upload}?{q}", body,
                                   _auth({"Content-Type": f"multipart/related; boundary={b}"}))
        urllib.request.urlopen(r, timeout=30).read()


def id_token(audience):
    """Google ID token for a private Cloud Run service (the CORS proxy). It lasts 1 hour; renew after 50 minutes."""
    value, exp = _ids.get(audience, ("", 0.0))
    if time.time() > exp:
        r = urllib.request.Request(f"{IDENTITY}?{urlencode({'audience': audience})}", headers={"Metadata-Flavor": "Google"})
        value = urllib.request.urlopen(r, timeout=5).read().decode()
        _ids[audience] = (value, time.time() + 3000)
    return value


def gpu_post(url, body):
    """POST to <proxy>/<platform>/v1beta/interactions. The audience is the proxy URL (scheme and host)."""
    u = urlsplit(url)
    headers = {"Authorization": f"Bearer {id_token(f'{u.scheme}://{u.netloc}')}", "Content-Type": "application/json"}
    r = urllib.request.Request(url, json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(r, timeout=GPU_TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def sign_blob(sa_email):
    url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{sa_email}:signBlob"

    def sign(data):
        body = json.dumps({"payload": base64.b64encode(data).decode()}).encode()
        r = urllib.request.Request(url, body, _auth({"Content-Type": "application/json"}))
        return base64.b64decode(json.load(urllib.request.urlopen(r, timeout=10))["signedBlob"])

    return sign
