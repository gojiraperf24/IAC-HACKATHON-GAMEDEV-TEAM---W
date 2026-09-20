"""LAN auto-discovery: lets a client find a Terminal Mafia server on the
same network without the host having to read out their IP address.

A tiny UDP broadcast/reply exchange alongside the main TCP game protocol -
the client broadcasts a discovery request and any server listening replies
with its game port; the client takes the reply's source address as the
host IP. Best-effort only: some networks (notably phone hotspots with
client isolation) block broadcast traffic between devices, so callers
should always fall back to manual entry when find_server() returns None.
"""
import socket

DISCOVERY_PORT = 54545
REQUEST = b"TERMINAL_MAFIA_DISCOVER"
REPLY_PREFIX = b"TERMINAL_MAFIA_HERE:"


def respond_forever(game_port):
    """Server side: answer discovery broadcasts with our game port. Runs
    until the process exits - meant to be started in a daemon thread."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", DISCOVERY_PORT))
    except OSError:
        return
    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except OSError:
            return
        if data == REQUEST:
            try:
                sock.sendto(REPLY_PREFIX + str(game_port).encode(), addr)
            except OSError:
                pass


def find_server(timeout=1.5):
    """Client side: broadcast a discovery request and wait for one reply.
    Returns (host, port), or None if nothing answered in time."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(REQUEST, ("255.255.255.255", DISCOVERY_PORT))
        data, addr = sock.recvfrom(1024)
    except OSError:
        return None
    finally:
        sock.close()
    if not data.startswith(REPLY_PREFIX):
        return None
    try:
        port = int(data[len(REPLY_PREFIX):])
    except ValueError:
        return None
    return addr[0], port
