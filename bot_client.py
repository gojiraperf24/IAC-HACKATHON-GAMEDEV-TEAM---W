"""Terminal Mafia - AI bot client, for filling seats during testing/demos.

Usage: python bot_client.py <host> <port> [name]
(or just python bot_client.py / double-click the .exe - it will try to
find the server automatically, then prompt if it can't)
"""
import random
import re
import socket
import sys
import time

from mafia import discovery, protocol

CHAT_LINES = [
    "I'm not sure who to trust yet.",
    "Someone's acting suspicious today.",
    "Let's think this through carefully.",
    "I have a feeling about someone...",
    "We need to work together to find the Grad Student.",
    "That vote yesterday felt off to me.",
    "I'll stay quiet and observe for now.",
]

REACTION_TO_BEING_ACCUSED = [
    "Wait, {accuser} thinks it's me? I promise I'm not the Grad Student!",
    "{accuser}, why me? I've been nowhere near suspicious.",
    "I'm innocent, {accuser} - you're barking up the wrong tree.",
    "Really, {accuser}? That's a bold accusation with zero evidence.",
]

REACTION_TO_ACCUSATION = [
    "{accuser} accusing {target}... I can see it.",
    "Not sure I agree with {accuser} about {target}.",
    "{target} does seem a little quiet, {accuser} might be onto something.",
    "Interesting call, {accuser}. I'll be watching {target}.",
]

REACTION_TO_WARDEN_REPORT = [
    "That Warden's report on {name} is definitely worth talking about.",
    "{name} being reported missing... that's not nothing.",
    "I keep thinking about the Warden's report on {name}.",
    "We can't just ignore that {name}'s room was empty.",
]

REACTION_TO_ELIMINATION = [
    "I can't believe we just lost {name}...",
    "Losing {name} changes things.",
    "{name} being gone worries me.",
    "RIP {name}. Let's stay sharp.",
]

ELIMINATED_RE = re.compile(r"^(.+) has been voted out!$")
INFECTED_RE = re.compile(r"^(.+) never woke up this morning\.\.\.$")
WARDEN_RE = re.compile(r"^\[WARDEN'S REPORT\] (.+) was reported missing")
ACCUSE_RE = re.compile(r"^\[ALERT\] (.+) publicly accuses (.+)! Suspicion board:")


def pick_chat_line(state, name):
    """React to whatever's most relevant right now, falling back to a
    generic line - weighted so it's responsive but not deterministic."""
    accuser = state.pop("accused_me_by", None)
    if accuser and random.random() < 0.7:
        return random.choice(REACTION_TO_BEING_ACCUSED).format(accuser=accuser)

    flagged = state.get("warden_flag")
    if flagged and random.random() < 0.35:
        return random.choice(REACTION_TO_WARDEN_REPORT).format(name=flagged)

    accusation = state.get("last_accusation")
    if accusation and accusation[1] != name and random.random() < 0.3:
        return random.choice(REACTION_TO_ACCUSATION).format(accuser=accusation[0], target=accusation[1])

    eliminated = state.get("last_eliminated")
    if eliminated and random.random() < 0.25:
        return random.choice(REACTION_TO_ELIMINATION).format(name=eliminated)

    return random.choice(CHAT_LINES)


def pick_accuse_target(state, name):
    """Mostly picks anyone, but leans toward whoever the Warden flagged -
    bots treat that as real evidence, not a sure thing."""
    others = [n for n in state["known_names"] if n != name]
    if not others:
        return None
    flagged = state.get("warden_flag")
    if flagged and flagged in others and random.random() < 0.6:
        return flagged
    return random.choice(others)


def main():
    if len(sys.argv) >= 3:
        host = sys.argv[1]
        port = int(sys.argv[2])
        name = sys.argv[3] if len(sys.argv) > 3 else f"Bot{random.randint(100, 999)}"
    else:
        # No <host> <port> passed on the command line - this happens when
        # the .exe is launched by double-clicking it rather than from a
        # terminal (or from server.py's --bots, which always passes args
        # and so never hits this branch).
        print("Looking for a server on this network...")
        found = discovery.find_server()
        if found:
            host, port = found
            print(f"Found server at {host}:{port}.")
        else:
            print("No server found automatically - enter it manually.")
            host = input("Server IP address (blank for 127.0.0.1): ").strip() or "127.0.0.1"
            while True:
                port_text = input("Port (blank for 5050): ").strip() or "5050"
                try:
                    port = int(port_text)
                    break
                except ValueError:
                    print("Enter a number for the port.")
        name = f"Bot{random.randint(100, 999)}"

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
    except OSError as e:
        print(f"Could not connect to {host}:{port} ({e}).")
        input("Press Enter to exit.")
        return
    reader = protocol.LineReader()
    state = {"name_sent": False, "known_names": set()}

    def send(obj):
        try:
            sock.sendall(protocol.encode(obj))
        except OSError:
            pass

    def handle(msg):
        mtype = msg.get("type")

        if mtype == "lobby":
            state["known_names"].update(msg.get("players", []))
            # If a bot happens to be host (e.g. solo testing with all bots),
            # nudge the lobby along once enough players have joined. This is
            # a harmless no-op ('start' is just chat) when the bot isn't host.
            if len(msg.get("players", [])) >= msg.get("min_players", 4):
                time.sleep(random.uniform(1.5, 3.0))
                send({"type": "input", "text": "start"})

        elif mtype == "chat":
            sender = msg.get("from", "").replace("[spectator] ", "")
            if sender:
                state["known_names"].add(sender)

        elif mtype == "text":
            text = msg.get("text", "")

            m = ACCUSE_RE.match(text)
            if m:
                accuser, target = m.group(1), m.group(2)
                state["last_accusation"] = (accuser, target)
                if target == name:
                    state["accused_me_by"] = accuser

            m = WARDEN_RE.match(text)
            if m:
                state["warden_flag"] = m.group(1)

            m = ELIMINATED_RE.match(text) or INFECTED_RE.match(text)
            if m:
                eliminated = m.group(1)
                state["last_eliminated"] = eliminated
                if state.get("warden_flag") == eliminated:
                    state["warden_flag"] = None

            if not state["name_sent"] and "name" in text.lower():
                time.sleep(random.uniform(0.2, 0.8))
                send({"type": "input", "text": name})
                state["name_sent"] = True
            elif "Discussion phase" in text:
                time.sleep(random.uniform(2.0, 6.0))
                target = pick_accuse_target(state, name) if random.random() < 0.4 else None
                if target:
                    send({"type": "input", "text": f"accuse {target}"})
                else:
                    send({"type": "input", "text": pick_chat_line(state, name)})
            elif "last words" in text.lower() and text.startswith("You have been eliminated"):
                time.sleep(random.uniform(0.5, 2.0))
                send({"type": "input", "text": random.choice(["It wasn't me!", "You'll regret this.", "Good luck, village."])})

        elif mtype == "prompt":
            options = msg.get("options", [])
            kind = msg.get("kind")
            time.sleep(random.uniform(1.0, 3.0))
            if options and random.random() > 0.1:
                choice = None
                if kind == "vote":
                    flagged = state.get("warden_flag")
                    if flagged and random.random() < 0.6:
                        choice = next((o for o in options if o["name"] == flagged), None)
                if choice is None:
                    choice = random.choice(options)
                send({"type": "input", "text": str(choice["num"])})
            else:
                send({"type": "input", "text": "skip"})

    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            for msg in reader.feed(data):
                handle(msg)
    except OSError:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
