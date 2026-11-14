import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol


class RawStore(Protocol):
    def capture(self, source: Path) -> tuple[str, str]: ...
    def locate(self, key: str) -> Path: ...


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def capture(self, source):
        self.root.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        with source.open("rb") as incoming, tempfile.NamedTemporaryFile(dir=self.root, delete=False) as temp:
            scratch = Path(temp.name)
            try:
                while block := incoming.read(1024 * 1024):
                    hasher.update(block)
                    temp.write(block)
                temp.flush()
                os.fsync(temp.fileno())
            except BaseException:
                temp.close()
                scratch.unlink()
                raise
        key = hasher.hexdigest()
        destination = self.locate(key)
        try:
            destination.parent.mkdir(exist_ok=True)
            try:
                os.link(scratch, destination)
            except FileExistsError:
                if file_hash(destination) != key:
                    raise ValueError("Raw storage integrity check failed")
        finally:
            scratch.unlink()
        return key, key

    def locate(self, key):
        if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
            raise ValueError("Invalid raw storage key")
        return self.root / key[:2] / key
