"""Integration tests: spin up a real GameServer on a loopback socket and
throw malformed/oversized/adversarial input at it, confirming a bad
client can never take the game down for everyone else.

Run with: python -m unittest discover tests
"""
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mafia.game import GameServer


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerResilienceTests(unittest.TestCase):
    def setUp(self):
        self.port = _free_port()
        self.server = GameServer(host="127.0.0.1", port=self.port, min_players=4)
        threading.Thread(target=self.server.run, daemon=True).start()
        time.sleep(0.3)

    def _connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        return s

    def _still_accepting(self):
        s = self._connect()
        s.sendall(json.dumps({"type": "input", "text": "HealthCheck"}).encode() + b"\n")
        time.sleep(0.2)
        s.settimeout(1.0)
        try:
            data = s.recv(4096)
        except socket.timeout:
            data = b""
        s.close()
        return len(data) > 0

    def test_survives_non_json_garbage_bytes(self):
        s = self._connect()
        s.sendall(b"\xff\xfe\x00\x01not json at all, no newline either")
        time.sleep(0.2)
        s.close()
        self.assertTrue(self._still_accepting())

    def test_survives_malformed_json_line(self):
        s = self._connect()
        s.sendall(b'{"type": "input", "text": \n')  # truncated/invalid JSON
        s.sendall(b"also not json\n")
        time.sleep(0.2)
        s.close()
        self.assertTrue(self._still_accepting())

    def test_survives_oversized_payload(self):
        s = self._connect()
        huge = "A" * 200_000
        s.sendall(json.dumps({"type": "input", "text": huge}).encode() + b"\n")
        time.sleep(0.3)
        s.close()
        self.assertTrue(self._still_accepting())

    def test_survives_missing_and_wrong_type_fields(self):
        s = self._connect()
        s.sendall(b'{"type": "input"}\n')  # no "text" key
        s.sendall(json.dumps({"type": "input", "text": 12345}).encode() + b"\n")  # int, not str
        s.sendall(json.dumps({"type": "input", "text": None}).encode() + b"\n")   # null
        time.sleep(0.2)
        s.close()
        self.assertTrue(self._still_accepting())

    def test_survives_unknown_message_type(self):
        s = self._connect()
        s.sendall(json.dumps({"type": "totally_unknown", "payload": [1, 2, 3]}).encode() + b"\n")
        time.sleep(0.2)
        s.close()
        self.assertTrue(self._still_accepting())

    def test_survives_abrupt_disconnect_mid_name_entry(self):
        s = self._connect()
        s.close()  # never even sends a name
        self.assertTrue(self._still_accepting())


if __name__ == "__main__":
    unittest.main()
