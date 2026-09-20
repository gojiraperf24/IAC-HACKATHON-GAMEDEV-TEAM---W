"""Terminal Mafia - host/server entry point.

Usage:
  python server.py [--port 5050] [--min-players 4] [--bots 3]

Run this on the machine that will host the game, then have other players
run `python client.py <host-ip> <port>` from their own terminals (on the
same machine, or anywhere on the same local network / hotspot).
"""
import argparse
import sys
import threading
import time

from mafia import discovery
from mafia.game import GameServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def main():
    parser = argparse.ArgumentParser(description="Terminal Mafia server")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--min-players", type=int, default=4)
    parser.add_argument("--bots", type=int, default=0,
                         help="Number of AI bot players to auto-connect (for solo testing/demos)")
    args = parser.parse_args()

    server = GameServer(host=args.host, port=args.port, min_players=args.min_players)

    threading.Thread(target=discovery.respond_forever, args=(args.port,), daemon=True).start()

    if args.bots > 0:
        def spawn_startup_bots():
            time.sleep(1.0)  # give the listen socket time to bind first
            error = server.spawn_bots(args.bots)
            if error:
                print(f"[server] --bots requested, but {error}")
        threading.Thread(target=spawn_startup_bots, daemon=True).start()

    print(f"Terminal Mafia server starting on {args.host}:{args.port}")
    print("Share your local IP address and this port with other players on the same network.")
    print("Players connect with: python client.py <your-ip> " + str(args.port))
    server.run()


if __name__ == "__main__":
    main()
