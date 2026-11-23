#!/usr/bin/env python3
"""Copy the weights of a model from the GCS weights bucket to its Runpod network volume (the Runpod S3 API).

Run from anywhere (loads the repo .env itself; no direnv needed), after terraform apply:
  ./scripts/runpod-weights.py deployments/<name> --dry-run   # list what it would copy
  ./scripts/runpod-weights.py deployments/<name> --cloud     # copy in a Cloud Build job (fast network; recommended)
  ./scripts/runpod-weights.py deployments/<name>             # copy from this computer (needs a fast upload)

It reads `terraform output -json runpod_volumes` ({dir, volumes = [{id, data_center}]}) and `weights_gcs`
(gs://<bucket>/<dir>/). Each GCS object goes to s3://<volume id>/<dir>/<name> on every volume, so the worker sees
/runpod-volume/<dir>/<name>, the same layout as on Vertex AI. Each part (16 MiB) is 1 GCS range read and 1 S3 upload, with retries; nothing goes to the local disk.
A file that is on the volume with the same size is skipped, so a second run copies only what is missing or changed.
The script never deletes on the volume.

Needs in .env: RUNPOD_S3_ACCESS_KEY and RUNPOD_S3_SECRET_KEY (Runpod console, Settings, "S3 API keys"; not the
Runpod API key), and the GCP service account of .env for gcloud (the GCS read). The keys are never printed.
--cloud: the Cloud Build job reads the keys from the infra/core secrets runpod-s3-access-key and runpod-s3-secret-key
(apply infra/core after hcp-sync.py) and runs this file with --volume-id, --data-center, --dir and --source.
"""
import argparse, datetime, hashlib, hmac, json, os, pathlib, shutil, subprocess, sys, time, urllib.error, urllib.request
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Runpod allows parts up to 500 MB, but uploads through its Cloudflare front often break (broken pipe, reset) on big
# bodies. Small parts lose little on a retry.
PART = 16 * 1024 * 1024
TRIES = 5
NET_ERRORS = (urllib.error.URLError, ConnectionError, TimeoutError)
GCS = "https://storage.googleapis.com/storage/v1"
META_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
# Cloudflare in front of the Runpod S3 API blocks the default Python-urllib agent (answer 403 "error code: 1010").
USER_AGENT = "custom-models-runpod-weights/1.0"


def load_env():
    """Minimal .env reader (same as hcp-sync.py). Values already in the environment win."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v[:1] in "\"'":
            v = v[1:].split(v[0])[0]
        else:
            v = v.split(" #")[0].strip()
        os.environ.setdefault(k.strip(), v)


def env_like_envrc():
    """The parts of .envrc that terraform and gcloud need here (as in deploy.py)."""
    E = os.environ
    if E.get("GCP_PROJECT_ID"):
        E.setdefault("TF_VAR_project_id", E["GCP_PROJECT_ID"])
    if E.get("GOOGLE_APPLICATION_CREDENTIALS"):
        E.setdefault("CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE", E["GOOGLE_APPLICATION_CREDENTIALS"])
        E.setdefault("CLOUDSDK_CONFIG", str(ROOT / ".gcloud"))


def output(d, name):
    r = subprocess.run(["terraform", "output", "-json", name], cwd=d, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"terraform output {name} failed in {d} (applied? terraform init done?):\n{r.stderr}")
    return json.loads(r.stdout)


# --- AWS Signature Version 4 (the Runpod S3 API) ---------------------------------------------------------------

def retry(fn, what):
    """fn() with TRIES tries on a network error, with a wait of 2, 4, 8 ... seconds between them."""
    for attempt in range(TRIES):
        try:
            return fn()
        except NET_ERRORS as e:
            if attempt == TRIES - 1:
                raise
            print(f"    {what}: {e}; retry {attempt + 1}", flush=True)
            time.sleep(2 ** (attempt + 1))


def _hmac(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sign_v4(method, host, path, query, headers, payload_hash, access, secret, region, now):
    """Return the request headers with Authorization. path: already URI-encoded. query: dict. headers: lower-case
    names, without host, x-amz-date and x-amz-content-sha256 (this function adds them)."""
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    h = {**headers, "host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash}
    names = sorted(h)
    canonical_query = "&".join(f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}" for k, v in sorted(query.items()))
    canonical = "\n".join([method, path, canonical_query, *(f"{k}:{str(h[k]).strip()}" for k in names), "",
                           ";".join(names), payload_hash])
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{secret}".encode(), day), region), "s3"), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
    return {**{k: v for k, v in h.items() if k != "host"}, "Authorization": auth}


class S3:
    """The few S3 calls the copy needs, path style: https://s3api-<dc>.runpod.io/<volume id>/<key>."""

    def __init__(self, data_center, bucket, access, secret):
        self.region, self.bucket, self.access, self.secret = data_center, bucket, access, secret
        self.host = f"s3api-{data_center.lower()}.runpod.io"

    def call(self, method, key, query=None, body=b"", headers=None):
        path = "/" + quote(f"{self.bucket}/{key}", safe="/-_.~")
        query = query or {}
        signed = sign_v4(method, self.host, path, query, headers or {}, hashlib.sha256(body).hexdigest(),
                         self.access, self.secret, self.region, datetime.datetime.now(datetime.timezone.utc))
        url = f"https://{self.host}{path}" + (f"?{urlencode(query)}" if query else "")
        req = urllib.request.Request(url, data=body if method in ("PUT", "POST") else None,
                                     headers={**signed, "User-Agent": USER_AGENT}, method=method)
        return urllib.request.urlopen(req, timeout=600)

    def size(self, key):
        """Size of an object on the volume, or None when it is not there."""
        try:
            with self.call("HEAD", key) as r:
                return int(r.headers["Content-Length"])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def put(self, key, data):
        self.call("PUT", key, body=data).close()

    def multipart(self, key, chunks):
        """Upload the chunks (bytes, in order) as 1 object. Abort the upload on any error."""
        with self.call("POST", key, {"uploads": ""}) as r:
            upload = _xml_text(r.read(), "UploadId")
        try:
            etags = []
            for n, data in enumerate(chunks, 1):
                def put_part(n=n, data=data):
                    with self.call("PUT", key, {"partNumber": n, "uploadId": upload}, data) as r:
                        return r.headers["ETag"]
                etags.append(retry(put_part, f"part {n}"))
            body = complete_xml(etags)
            self.call("POST", key, {"uploadId": upload}, body, {"content-type": "application/xml"}).close()
        except BaseException:
            try:
                self.call("DELETE", key, {"uploadId": upload}).close()
            finally:
                raise


def _xml_text(data, tag):
    for el in ElementTree.fromstring(data).iter():
        if el.tag.rsplit("}", 1)[-1] == tag:
            return el.text
    raise ValueError(f"no {tag} in the S3 answer")


def complete_xml(etags):
    parts = "".join(f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>" for n, e in enumerate(etags, 1))
    return f"<CompleteMultipartUpload>{parts}</CompleteMultipartUpload>".encode()


# --- GCS (the source) --------------------------------------------------------------------------------------------

_token = {"value": "", "at": 0.0}


def gcloud_token():
    """An access token, renewed every 10 minutes (it lasts 1 hour; a copy can take longer)."""
    if time.time() - _token["at"] > 600:
        if shutil.which("gcloud"):
            r = subprocess.run(["gcloud", "auth", "print-access-token"], text=True, capture_output=True)
            if r.returncode:
                sys.exit(f"gcloud auth print-access-token failed:\n{r.stderr}")
            value = r.stdout.strip()
        else:  # Cloud Build (--cloud): the token of the build service account
            req = urllib.request.Request(META_TOKEN, headers={"Metadata-Flavor": "Google"})
            value = json.load(urllib.request.urlopen(req, timeout=10))["access_token"]
        _token.update(value=value, at=time.time())
    return _token["value"]


def split_gs(uri):
    bucket, _, prefix = uri.removeprefix("gs://").partition("/")
    return bucket, prefix.rstrip("/") + "/"


def gcs_list(bucket, prefix, token):
    """[(name below prefix, size)] of the weights. Skips folder markers and the .cache/ of the weights-copy job."""
    out, page = [], None
    while True:
        q = {"prefix": prefix, "fields": "items(name,size),nextPageToken", **({"pageToken": page} if page else {})}
        req = urllib.request.Request(f"{GCS}/b/{bucket}/o?{urlencode(q)}", headers={"Authorization": f"Bearer {token}"})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        out += [(i["name"][len(prefix):], int(i["size"])) for i in d.get("items", [])
                if not i["name"].endswith("/") and "/.cache/" not in "/" + i["name"]]
        page = d.get("nextPageToken")
        if not page:
            return out


def ranges(size, part=PART):
    """[(first byte, last byte)] of the parts of an object of size bytes (HTTP Range is inclusive)."""
    return [(start, min(start + part, size) - 1) for start in range(0, size, part)]


def gcs_parts(url, size, token, part=PART):
    """The bytes of a GCS object, part by part. Each part is its own range request (no long stream to break).
    token: a function that returns a valid access token."""
    for first, last in ranges(size, part):
        def get(first=first, last=last):
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token()}", "Range": f"bytes={first}-{last}"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            if len(data) != last - first + 1:
                raise ConnectionError(f"GCS range {first}-{last}: got {len(data)} bytes")
            return data
        yield retry(get, f"GCS bytes {first}-{last}")


def to_copy(objects, sizes):
    """objects: [(name, size)]. sizes: name -> size on the volume (None: missing). Returns the objects to copy."""
    return [(n, s) for n, s in objects if sizes.get(n) != s]


CLOUD_IMAGE = "python:3.13-slim"  # no gcloud: gcloud_token() uses the metadata server of the build


def cloud_config(target, src, dry_run):
    """Cloud Build config that runs this file next to the data: 1 step per volume, all at the same time.
    The S3 keys come from Secret Manager."""
    project = os.environ["GCP_PROJECT_ID"]
    steps = [{"name": CLOUD_IMAGE, "id": v["data_center"], "waitFor": ["-"], "entrypoint": "python3",
              "args": ["-u", "runpod-weights.py", "--volume-id", v["id"], "--data-center", v["data_center"],
                       "--dir", target["dir"], "--source", src, *(["--dry-run"] if dry_run else [])],
              "secretEnv": ["RUNPOD_S3_ACCESS_KEY", "RUNPOD_S3_SECRET_KEY"]} for v in target["volumes"]]
    return {
        "steps": steps,
        "availableSecrets": {"secretManager": [
            {"versionName": f"projects/{project}/secrets/runpod-s3-access-key/versions/latest", "env": "RUNPOD_S3_ACCESS_KEY"},
            {"versionName": f"projects/{project}/secrets/runpod-s3-secret-key/versions/latest", "env": "RUNPOD_S3_SECRET_KEY"},
        ]},
        "timeout": "7200s",
        "options": {"logging": "CLOUD_LOGGING_ONLY"},
    }


def run_in_cloud(target, src, dry_run):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        (work / "runpod-weights.py").write_text(pathlib.Path(__file__).read_text())
        (work / "cloudbuild.json").write_text(json.dumps(cloud_config(target, src, dry_run)))
        region = os.environ.get("GCP_REGION", "us-central1")
        dcs = ", ".join(v["data_center"] for v in target["volumes"])
        print(f"Cloud Build: copy {src} to the volumes in {dcs}. It takes some minutes.", flush=True)
        r = subprocess.run(["gcloud", "builds", "submit", str(work), f"--config={work / 'cloudbuild.json'}", f"--region={region}",
                            f"--project={os.environ['GCP_PROJECT_ID']}"])
        sys.exit(r.returncode)


def copy_volume(vol, folder, src, dry_run, access, secret):
    """Copy the GCS folder src to s3://<vol id>/<folder>/. Skips files with the same size; never deletes."""
    s3 = S3(vol["data_center"], vol["id"], access, secret)
    bucket, prefix = split_gs(src)
    objects = gcs_list(bucket, prefix, gcloud_token())
    if not objects:
        sys.exit(f"no weights in {src} (run the weights-copy job first, see the deployment README)")
    key = lambda n: f"{folder}/{n}"
    todo = to_copy(objects, {n: s3.size(key(n)) for n, _ in objects})
    print(f"{src} -> s3://{vol['id']}/{folder}/ ({vol['data_center']}): {len(objects)} files, "
          f"{len(todo)} to copy ({sum(s for _, s in todo) / 1e9:.2f} GB)", flush=True)
    t0 = time.time()
    for n, s in todo:
        print(f"  {'would copy' if dry_run else 'copy'} {n} ({s / 1e6:.1f} MB)", flush=True)
        if dry_run:
            continue
        url = f"{GCS}/b/{bucket}/o/{quote(prefix + n, safe='')}?alt=media"
        parts = gcs_parts(url, s, gcloud_token)
        if s <= PART:
            data = next(parts, b"")
            retry(lambda: s3.put(key(n), data), n)
        else:
            s3.multipart(key(n), parts)
        if s3.size(key(n)) != s:
            sys.exit(f"{n}: the size on the volume is not {s} bytes after the copy")
    print(f"done {vol['data_center']}: {0 if dry_run else len(todo)} copied, {len(objects) - len(todo)} skipped "
          f"(same size on the volume) in {time.time() - t0:.0f} s", flush=True)


def main():
    load_env()
    env_like_envrc()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("deployment", nargs="?", help="deployments/<name> (reads the outputs runpod_volumes and weights_gcs)")
    ap.add_argument("--dry-run", action="store_true", help="list what would be copied, copy nothing")
    ap.add_argument("--cloud", action="store_true", help="run the copy in a Cloud Build job")
    ap.add_argument("--volume-id"), ap.add_argument("--data-center"), ap.add_argument("--dir"), ap.add_argument("--source")
    a = ap.parse_args()
    if a.volume_id:  # 1 step of the Cloud Build job: no terraform there
        target, src = {"dir": a.dir, "volumes": [{"id": a.volume_id, "data_center": a.data_center}]}, a.source
    elif a.deployment:
        d = pathlib.Path(a.deployment).resolve()
        target, src = output(d, "runpod_volumes"), output(d, "weights_gcs")
    else:
        ap.error("give deployments/<name>")
    if not target:
        sys.exit(f"{a.deployment} has no Runpod volume (platform_options.runpod.volume)")
    if a.cloud:
        run_in_cloud(target, src, a.dry_run)
    access, secret = os.environ.get("RUNPOD_S3_ACCESS_KEY"), os.environ.get("RUNPOD_S3_SECRET_KEY")
    if not access or not secret:
        sys.exit("RUNPOD_S3_ACCESS_KEY and RUNPOD_S3_SECRET_KEY must be set (.env; in Cloud Build: the infra/core secrets)")
    for vol in target["volumes"]:
        copy_volume(vol, target["dir"], src, a.dry_run, access.strip(), secret.strip())


if __name__ == "__main__":
    main()
