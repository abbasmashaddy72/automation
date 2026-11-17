#!/usr/bin/env python3
"""Read only a bounded GGUF metadata header to learn trained context size.

This does not load tensor data, require third-party packages, or start inference.
Unknown GGUF variants/unsafe metadata fail closed: caller must not guess a cap.
"""

from __future__ import annotations
from pathlib import Path
import struct

MAX_VALUES = 1_000_000
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_KV_PAIRS = 50000
MAX_ARRAY_ITEMS = 500000
PRIMITIVES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


class InvalidGGUF(ValueError):
    pass


class _Reader:
    def __init__(self, fp):
        self.fp = fp
        self.count = 0
        self.values = 0

    def get(self, n):
        if n < 0 or n > MAX_METADATA_BYTES - self.count:
            raise InvalidGGUF("GGUF metadata header exceeds safe limit")
        data = self.fp.read(n)
        if len(data) != n:
            raise InvalidGGUF("Truncated GGUF metadata")
        self.count += n
        return data

    def num(self, fmt):
        return struct.unpack("<" + fmt, self.get(struct.calcsize("<" + fmt)))[0]

    def string(self):
        size = self.num("Q")
        if size > 1024 * 1024:
            raise InvalidGGUF("Metadata string too long")
        return self.get(size).decode("utf-8", "replace")

    def value(self, kind, depth=0):
        self.values += 1
        if self.values > MAX_VALUES:
            raise InvalidGGUF("Too many GGUF metadata values")
        if depth > 4:
            raise InvalidGGUF("Nested metadata array exceeds safe limit")
        if kind in PRIMITIVES:
            if kind == 4:
                return self.num("I")
            if kind == 10:
                return self.num("Q")
            self.get(PRIMITIVES[kind])
            return None
        if kind == 8:
            return self.string()
        if kind == 9:
            item = self.num("I")
            length = self.num("Q")
            if length > MAX_ARRAY_ITEMS:
                raise InvalidGGUF("Metadata array too long")
            for _ in range(length):
                self.value(item, depth + 1)
            return None
        raise InvalidGGUF("Unrecognized GGUF metadata type")


def trained_context_from_gguf(path):
    """Return positive model context-length metadata or None when absent.

    Files are limited to the first 16 MiB of GGUF metadata regardless of tensor size.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".gguf":
        raise InvalidGGUF("Not an ordinary GGUF model file")
    with path.open("rb") as fp:
        r = _Reader(fp)
        if r.get(4) != b"GGUF":
            raise InvalidGGUF("GGUF signature missing")
        version = r.num("I")
        if not 2 <= version <= 3:
            raise InvalidGGUF("Unsupported GGUF version")
        r.num("Q")  # tensor count
        kv_count = r.num("Q")
        if kv_count > MAX_KV_PAIRS:
            raise InvalidGGUF("Too many GGUF metadata entries")
        fields = {}
        for _ in range(kv_count):
            key = r.string()
            kind = r.num("I")
            value = r.value(kind)
            if key == "general.architecture" or key.endswith(".context_length"):
                if key in fields:
                    raise InvalidGGUF("Duplicate context metadata")
                fields[key] = value
        arch = fields.get("general.architecture")
        context = (
            fields.get(arch + ".context_length") if isinstance(arch, str) else None
        )
        return context if isinstance(context, int) and 1 <= context <= 1048576 else None
