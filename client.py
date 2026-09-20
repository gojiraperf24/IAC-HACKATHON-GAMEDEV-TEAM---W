"""Terminal Mafia: campus intrigue - human player client.

Usage: python client.py <host> <port>
(or just python client.py / double-click the .exe - it will prompt for
the server address and port interactively)
"""
import socket
import sys
import threading
import time

from mafia import discovery, protocol
from mafia.colors import colorize

# How long to pause after printing a chat/text line, so a burst of several
# messages arriving at once (e.g. multiple bots talking back to back)
# doesn't all flash by instantly. Doesn't apply to prompts - those need an
# immediate reply, not a delay.
READ_DELAY = 0.5

# Legacy Windows consoles (default cmd.exe codepages) can't encode every
# Unicode character; without this, a single odd character in any chat/
# broadcast text would crash the client mid-game with UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

ASCII_BANNER = r"""
@@@@@ @@@ @   @ @@@@     @@@@@ @   @ @@@@@    @@@@@ @   @  @@@  @@@ @   @ @@@@@ @@@@@ @@@@  
@      @  @@  @ @   @      @   @   @ @        @     @@  @ @      @  @@  @ @     @     @   @ 
@@@@   @  @ @ @ @   @      @   @@@@@ @@@@     @@@@  @ @ @ @  @@  @  @ @ @ @@@@  @@@@  @@@@  
@      @  @  @@ @   @      @   @   @ @        @     @  @@ @   @  @  @  @@ @     @     @  @  
@     @@@ @   @ @@@@       @   @   @ @@@@@    @@@@@ @   @  @@@  @@@ @   @ @@@@@ @@@@@ @   @ 
"""

PHASE_BANNERS = {
    "night": ("AFTER HOURS", "blue"),
    "day_discuss": ("OFFICE HOURS", "yellow"),
    "vote": ("DEPARTMENT VOTE", "red"),
    "game_over": ("FINAL GRADES", "green"),
}

PROMPT_LABELS = {
    "infect": "SELECT STUDENT TO INFLUENCE",
    "save": "SELECT PLAYER TO PROTECT",
    "inspect": "SELECT A PLAYER'S ROOM TO CHECK",
    "steal": "SELECT PLAYER TO DEDUCT A POINT FROM",
    "vote": "CAST YOUR VOTE - WHO IS THE GRAD STUDENT?",
}


def phase_banner(phase, round_no):
    label, color = PHASE_BANNERS.get(phase, (phase.upper(), None))
    suffix = f" - CYCLE {round_no}" if round_no else ""
    line = "=" * 60
    print("\n" + colorize(line, color))
    print(colorize(f">> {label}{suffix} <<".center(60), "bold"))
    print(colorize(line, color))


def handle_message(msg):
    mtype = msg.get("type")

    if mtype == "phase":
        phase_banner(msg.get("phase"), msg.get("round"))

    elif mtype == "text":
        print("\n" + colorize(msg.get("text", ""), msg.get("color")))

    elif mtype == "chat":
        print(f"\n{colorize(msg.get('from', '?') + ':', 'bold')} {msg.get('text', '')}")

    elif mtype == "lobby":
        names = msg.get("players", [])
        print("\n" + colorize(
            f"Students connected ({len(names)}/{msg.get('min_players')} min): " + ", ".join(names), "cyan"))

    elif mtype == "role":
        role = msg.get("role")
        print()
        print(colorize(f"=== YOUR ROLE: {role.upper()} ===", "bold"))
        print(colorize(msg.get("description", ""), "magenta"))

    elif mtype == "prompt":
        label = PROMPT_LABELS.get(msg.get("kind"), msg.get("text", "Choose:"))
        print()
        print(colorize(f"> {label}", "yellow"))
        for opt in msg.get("options", []):
            print(f"  {opt['num']}. {opt['name']}")
        print(colorize(f"(You have {msg.get('time_limit')}s. Type a number, a name, or 'skip'.)", "dim"))
        print("> ", end="", flush=True)

    elif mtype == "game_over":
        winner = msg.get("winner")
        winner_label = "THE GRAD STUDENT" if winner == "grad_student" else "THE STUDENTS"
        print("\n" + colorize(f">> {winner_label} WIN <<", "bold"))
        print(colorize("Roles revealed:", "cyan"))
        scores = msg.get("scores", {})
        for name, role in msg.get("roles", {}).items():
            print(f"  {name}: {role} (score: {scores.get(name, 0)})")


def receiver(sock, disconnected):
    reader = protocol.LineReader()
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            for msg in reader.feed(data):
                handle_message(msg)
                if msg.get("type") in ("chat", "text"):
                    time.sleep(READ_DELAY)
    except OSError:
        pass
    # Don't force-exit here: the main thread is likely still sitting in
    # input() so the player can read the final game-over screen (roles,
    # scores) for as long as they want - it only unblocks once they
    # actually press Enter, checked against this flag rather than a
    # failed send (which can race the server's own close timing).
    disconnected.set()
    print("\n" + colorize("Disconnected from server. Press Enter to exit.", "yellow"))


def main():
    print(colorize(ASCII_BANNER, "cyan"))

    if len(sys.argv) >= 3:
        host = sys.argv[1]
        port = int(sys.argv[2])
    else:
        # No <host> <port> passed on the command line - this happens when the
        # .exe is launched by double-clicking it rather than from a terminal.
        # Try to find a server automatically (works on most LANs/hotspots;
        # some phone hotspots block broadcast traffic between devices), and
        # fall back to asking for it manually if nothing answers.
        print(colorize("Looking for a server on this network...", "dim"))
        found = discovery.find_server()
        if found:
            host, port = found
            print(colorize(f"Found server at {host}:{port}.", "green"))
        else:
            print(colorize("No server found automatically - enter it manually.", "yellow"))
            host = input("Server IP address (blank for 127.0.0.1): ").strip() or "127.0.0.1"
            while True:
                port_text = input("Port (blank for 5050): ").strip() or "5050"
                try:
                    port = int(port_text)
                    break
                except ValueError:
                    print("Enter a number for the port.")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
    except OSError as e:
        print(colorize(f"Could not connect to {host}:{port} ({e}).", "red"))
        input("Press Enter to exit.")
        return
    print(colorize(f"Connected to {host}:{port}.", "green"))

    disconnected = threading.Event()
    threading.Thread(target=receiver, args=(sock, disconnected), daemon=True).start()

    try:
        while True:
            line = input()
            if disconnected.is_set():
                break
            try:
                sock.sendall(protocol.encode({"type": "input", "text": line}))
            except OSError:
                break
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
