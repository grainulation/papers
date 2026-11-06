"""Canonical JSON, record ids and URL canonicalization for evidence records.

Spec: v2/evidence-verification-spec.md §1.1, §3.5.

canonical_json(obj) must equal serde_json's output for the same value
(BTreeMap key order, compact separators, no ASCII escaping). That holds
because records contain no floats and sanitized strings contain no control
characters other than "\\n". Floats are rejected outright.

Stdlib only.
"""

import hashlib
import json
import re
import urllib.parse

__all__ = [
    "canonical_json",
    "canonical_bytes",
    "sha256_hex",
    "sha256_hex16",
    "record_id",
    "canonical_url",
    "git_blob_sha1",
    "CanonicalError",
]


class CanonicalError(ValueError):
    pass


def _check(obj, path="$"):
    if obj is None or isinstance(obj, (bool, str)):
        return
    if isinstance(obj, int):
        return
    if isinstance(obj, float):
        raise CanonicalError(f"float not allowed in a sealed record at {path}")
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key at {path}")
            _check(v, f"{path}.{k}")
        return
    raise CanonicalError(f"unsupported type {type(obj).__name__} at {path}")


def canonical_json(obj):
    """Sorted keys, compact separators, UTF-8 (no ASCII escaping), no floats."""
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(obj):
    return canonical_json(obj).encode("utf-8")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def sha256_hex16(data):
    """First 16 bytes of SHA-256, hex (128 bits), like bran/src/ir.rs sha256_hex16."""
    return hashlib.sha256(data).digest()[:16].hex()


def record_id(record):
    return sha256_hex16(canonical_bytes(record))


def git_blob_sha1(data):
    """Same value `git hash-object` prints, computed without invoking git."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


_TRACKING = re.compile(r"^(utm_[a-z0-9_]*|fbclid|gclid)$", re.I)
CANONICAL_URL_VERSION = "canon-url/1"


def canonical_url(url):
    """Spec §1.1 canonical_url: lowercase scheme+host, drop default port,
    drop fragment, drop utm_*/fbclid/gclid, strip one trailing '/' on
    non-root paths. Query parameter order is otherwise preserved."""
    if url is None:
        return None
    p = urllib.parse.urlsplit(url)
    scheme = p.scheme.lower()
    host = (p.hostname or "").lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = p.port
    default = {"http": 80, "https": 443}.get(scheme)
    netloc = host if port is None or port == default else f"{host}:{port}"
    # userinfo is dropped: credentials never belong in a key
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    # keep raw query pieces (no re-encoding) except tracking parameters
    pieces = [s for s in p.query.split("&") if s and not _TRACKING.match(s.split("=", 1)[0])]
    return urllib.parse.urlunsplit((scheme, netloc, path, "&".join(pieces), ""))
