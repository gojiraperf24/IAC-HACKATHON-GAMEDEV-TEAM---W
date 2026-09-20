"""Newline-delimited JSON wire protocol shared by server and clients."""
import json


def encode(obj):
    return (json.dumps(obj) + "\n").encode("utf-8")


class LineReader:
    """Buffers raw socket bytes and yields decoded JSON messages line by line."""

    def __init__(self):
        self._buf = ""

    def feed(self, data: bytes):
        self._buf += data.decode("utf-8", errors="ignore")
        messages = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return messages
