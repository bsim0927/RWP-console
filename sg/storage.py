"""Supabase Storage over plain HTTP: the private bucket that holds the fund files when the console is hosted.

SUPABASE_URL (https://<project-ref>.supabase.co) and SUPABASE_SERVICE_ROLE_KEY name the project; the key never
leaves the server. Files go in under a hash of their path (object_key), because object keys cannot hold every
character a file name can; data_files maps one to the other. Files over 6 MB use Storage's resumable (TUS)
upload in 6 MB chunks, as Supabase recommends for large files.
"""

import base64
import hashlib
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .env import load_env

BUCKET = os.environ.get("RWP_STORAGE_BUCKET", "fund-files")
CHUNK = 6 * 1024 * 1024  # Supabase's required chunk size for resumable uploads


class StorageError(RuntimeError):
    pass


def _config():
    load_env()
    url, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise StorageError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to reach Storage")
    return url, key


def _call(method, url, body=None, headers=None):
    """(status, response headers, body bytes); HTTP errors are returned, not raised."""
    _, key = _config()
    if urlsplit(url).scheme != "https":  # the service key only ever goes to the project over TLS
        raise StorageError(f"refusing a non-https Storage URL: {url}")
    h = {"apikey": key, "Authorization": f"Bearer {key}", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=h, method=method)  # noqa: S310  https checked above
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310  https checked above
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def object_key(path):
    """The object a data-root path is stored as: a hash of the path, keeping the extension for content type."""
    return hashlib.sha256(path.encode()).hexdigest()[:40] + Path(path).suffix.lower()


def ensure_bucket():
    """Create the private bucket unless it exists."""
    url, _ = _config()
    body = json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode()
    status, _, out = _call("POST", f"{url}/storage/v1/bucket", body, {"Content-Type": "application/json"})
    if status not in (200, 201) and b"already exists" not in out.lower():
        raise StorageError(f"could not create bucket {BUCKET}: HTTP {status} {out[:300]!r}")


def upload(key, file):
    """Put a local file at key, replacing any object already there."""
    file = Path(file)
    ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    if file.stat().st_size <= CHUNK:
        url, _ = _config()
        status, _, out = _call(
            "POST",
            f"{url}/storage/v1/object/{BUCKET}/{key}",
            file.read_bytes(),
            {"Content-Type": ctype, "x-upsert": "true"},
        )
        if status not in (200, 201):
            raise StorageError(f"upload of {file.name} failed: HTTP {status} {out[:300]!r}")
        return
    _upload_resumable(key, file, ctype)


def _upload_resumable(key, file, ctype):
    url, _ = _config()
    ref = (urlsplit(url).hostname or "").split(".")[0]
    endpoint = f"https://{ref}.storage.supabase.co/storage/v1/upload/resumable"
    b64 = lambda s: base64.b64encode(s.encode()).decode()
    meta = f"bucketName {b64(BUCKET)},objectName {b64(key)},contentType {b64(ctype)},cacheControl {b64('3600')}"
    size = file.stat().st_size
    status, headers, out = _call(
        "POST",
        endpoint,
        b"",
        {"Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": meta, "x-upsert": "true"},
    )
    location = headers.get("Location") or headers.get("location")
    if status != 201 or not location:
        raise StorageError(f"could not start the upload of {file.name}: HTTP {status} {out[:300]!r}")
    offset = 0
    with file.open("rb") as fh:
        while offset < size:
            chunk = fh.read(CHUNK)
            status, headers, out = _call(
                "PATCH",
                location,
                chunk,
                {
                    "Tus-Resumable": "1.0.0",
                    "Upload-Offset": str(offset),
                    "Content-Type": "application/offset+octet-stream",
                },
            )
            if status != 204:
                raise StorageError(f"upload of {file.name} stopped at byte {offset}: HTTP {status} {out[:300]!r}")
            offset = int(headers.get("Upload-Offset") or headers.get("upload-offset") or offset + len(chunk))


def signed_url(key, seconds=3600):
    """A link to the object that works without credentials for `seconds`."""
    url, _ = _config()
    body = json.dumps({"expiresIn": seconds}).encode()
    status, _, out = _call(
        "POST", f"{url}/storage/v1/object/sign/{BUCKET}/{key}", body, {"Content-Type": "application/json"}
    )
    if status != 200:
        raise StorageError(f"could not sign {key}: HTTP {status} {out[:300]!r}")
    return f"{url}/storage/v1{json.loads(out)['signedURL']}"
