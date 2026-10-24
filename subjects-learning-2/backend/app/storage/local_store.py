import os
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.storage.content_hash import sha256_bytes


class LocalFilesystemContentStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (get_settings().data_dir / "objects")
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, category: str, data: bytes, suffix: str = "") -> tuple[str, str]:
        digest = sha256_bytes(data)
        relative = Path(category) / digest[:2] / f"{digest}{suffix}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return relative.as_posix(), digest

    def read_bytes(self, storage_key: str) -> bytes:
        return self.path_for(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self.path_for(storage_key)
        if path.exists():
            path.unlink()

    def path_for(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("非法存储路径")
        return candidate


store = LocalFilesystemContentStore()
