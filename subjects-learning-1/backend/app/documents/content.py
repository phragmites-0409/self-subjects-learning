import gzip
import json


def dumps_compressed(value: dict) -> bytes:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9)


def loads_compressed(data: bytes) -> dict:
    return json.loads(gzip.decompress(data).decode("utf-8"))
