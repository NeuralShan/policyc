"""Content-addressed local file storage.

Files are stored under their SHA-256, never under the client-supplied filename, so uploads cannot
escape the storage root. The interface is small on purpose: an object store (MinIO/GCS) can
replace it later without touching callers.
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO

CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    pass


@dataclass(frozen=True)
class StoredFile:
    key: str  # relative to the storage root, always forward slashes
    sha256: str
    size_bytes: int


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, namespace: str, stream: BinaryIO, suffix: str, max_bytes: int) -> StoredFile:
        """Stream ``stream`` to disk, hashing as it goes; abort once ``max_bytes`` is exceeded."""
        if not namespace.replace("_", "").isalnum():
            raise ValueError(f"invalid storage namespace: {namespace!r}")
        if suffix and not (suffix.startswith(".") and suffix[1:].isalnum()):
            raise ValueError(f"invalid suffix: {suffix!r}")

        digest = hashlib.sha256()
        size = 0
        target_dir = self.root / namespace
        target_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target_dir, prefix=".upload-")
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise UploadTooLarge(f"file exceeds {max_bytes // (1024 * 1024)} MB")
                    digest.update(chunk)
                    out.write(chunk)
            sha = digest.hexdigest()
            key = f"{namespace}/{sha}{suffix.lower()}"
            final = self.root / key
            if final.exists():
                os.unlink(tmp_name)
            else:
                os.replace(tmp_name, final)
            return StoredFile(key=key, sha256=sha, size_bytes=size)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def path(self, key: str) -> Path:
        resolved = (self.root / PurePath(key)).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"storage key escapes root: {key!r}")
        return resolved

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
