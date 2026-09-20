"""Core game server: connection handling and the night/day game loop.

All game-state mutation happens on a single thread (the thread that calls
GameServer.run). Per-connection reader threads only ever push messages onto
a thread-safe queue; they never touch shared state directly. This keeps the
game logic free of locking concerns while still supporting real concurrent
socket I/O across many players.
"""
import os
import queue
import random
import socket
import subprocess
import sys
import threading
import time
from collections import Counter

from mafia import protocol, roles


def _bot_command():
    """Build the subprocess command for a bot client, working both when
    running from source and when frozen into a standalone .exe (where
    sys.executable is this program itself, not a Python interpreter)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for candidate in ("terminal-mafia-bot.exe", "bot_client.exe"):
            path = os.path.join(exe_dir, candidate)
            if os.path.isfile(path):
                return [path]
        return None
    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, os.path.join(server_dir, "bot_client.py")]


class Player:
    def __init__(self, pid, conn, addr):
        self.id = pid
        self.conn = conn
        self.addr = addr
        self.name = None
        self.role = None
        self.alive = True
        self.connected = True
        self.is_host = False
        self.spectator = False
        self.score = 0
        # Input routing state: what kind of reply we're expecting next.
        self.pending = None          # None | "name" | "action"
        self.pending_kind = None     # "infect" | "save" | "inspect" | "steal" | "vote"
        self.pending_options = []    # list[Player] the reply must resolve to


class GameServer:
    NIGHT_TIME = 35
    DAY_DISCUSS_TIME = 45
    DAY_VOTE_TIME = 30
    LAST_WORDS_TIME = 15
    MAX_BOTS_PER_REQUEST = 20

    def __init__(self, host="0.0.0.0", port=5050, min_players=4):
        self.host = host
        self.port = port
        self.min_players = min_players

        self.players = {}
        self.inbound = queue.Queue()
        self._next_id = 1

        self.log = []
        self.round = 0
        self.game_started = False
        self.host_id = None
        self._no_elim_streak = 0
        self.pending_infection_id = None
        self.pending_suspicion_id = None
        self._srv_sock = None

    # ------------------------------------------------------------------ #
    # Networking plumbing
    # ------------------------------------------------------------------ #
    def run(self):
        self._srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv_sock.bind((self.host, self.port))
        self._srv_sock.listen()
        threading.Thread(target=self._accept_loop, daemon=True).start()

        try:
            self.lobby_phase()
            self.assign_roles()
            while True:
                self.night_phase()
                if self.check_win():
                    break
                self.day_phase()
                if self.check_win():
                    break
        finally:
            time.sleep(2)
            for p in list(self.players.values()):
                # shutdown() first: each connection also has a
                # _client_reader thread blocked in recv() on this same
                # socket, and close() alone doesn't reliably unblock that
                # and send the client a FIN - the client can be left
                # thinking it's still connected indefinitely. shutdown()
                # forces that immediately, close() then releases the fd.
                try:
                    p.conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    p.conn.close()
                except OSError:
                    pass
            try:
                self._srv_sock.close()
            except OSError:
                pass

    def spawn_bots(self, n):
        """Launch n bot_client processes that connect to this server on
        localhost. Returns None on success, or an error string. Runs the
        actual spawning on a background thread so the caller (the game
        loop) never blocks on subprocess startup."""
        bot_cmd = _bot_command()
        if bot_cmd is None:
            return "no bot_client.py/terminal-mafia-bot.exe found next to this program."

        def _spawn():
            for _ in range(n):
                subprocess.Popen(bot_cmd + ["127.0.0.1", str(self.port)])
                time.sleep(0.2)
        threading.Thread(target=_spawn, daemon=True).start()
        return None

    def _accept_loop(self):
        # This runs on its own thread, so it must never touch self.players
        # directly - the main game-loop thread is the sole owner of that
        # dict (see module docstring). The new Player is handed off through
        # the inbound queue and only inserted once the main thread processes
        # the __connected__ event, in _handle_common.
        while True:
            try:
                conn, addr = self._srv_sock.accept()
            except OSError:
                return
            pid = self._next_id
            self._next_id += 1
            p = Player(pid, conn, addr)
            threading.Thread(target=self._client_reader, args=(p,), daemon=True).start()
            self.inbound.put((pid, {"type": "__connected__", "player": p}))

    def _client_reader(self, p):
        reader = protocol.LineReader()
        try:
            while True:
                data = p.conn.recv(4096)
                if not data:
                    break
                for msg in reader.feed(data):
                    self.inbound.put((p.id, msg))
        except OSError:
            pass
        finally:
            self.inbound.put((p.id, {"type": "__disconnect__"}))

    def send_to(self, p, obj):
        try:
            p.conn.sendall(protocol.encode(obj))
        except OSError:
            p.connected = False

    def send_text(self, p, text, color=None):
        self.send_to(p, {"type": "text", "text": text, "color": color})

    def broadcast_text(self, text, color=None, exclude=None):
        for p in self.players.values():
            if p.connected and p.id != exclude:
                self.send_text(p, text, color)

    def broadcast_phase(self, phase, round_no=None):
        """Pure UI signal: lets clients render a themed banner for this
        phase. Carries no game logic of its own - safe to ignore."""
        for p in self.players.values():
            if p.connected:
                self.send_to(p, {"type": "phase", "phase": phase, "round": round_no})

    def _log(self, text):
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {text}")
        print(f"[server] {text}")

    # ------------------------------------------------------------------ #
    # Shared inbound-message handling
    # ------------------------------------------------------------------ #
    def _handle_common(self, pid, msg):
        """Handle connect/disconnect/name-entry. Returns True if the
        message was fully handled and needs no further action from the
        caller."""
        mtype = msg.get("type")

        if mtype == "__connected__":
            p = msg.get("player")
            if p is None:
                return True
            self.players[p.id] = p
            p.pending = "name"
            if self.game_started:
                p.spectator = True
                self.send_text(p, "The game is already in progress. Enter a name to join as a spectator:", "yellow")
            else:
                self.send_text(p, "Welcome to Terminal Mafia! Enter your name:", "cyan")
            return True

        if mtype == "__disconnect__":
            p = self.players.get(pid)
            if p:
                was_named = p.name is not None
                p.connected = False
                if p.alive:
                    p.alive = False
                if was_named:
                    self.broadcast_text(f"{p.name} has disconnected.", "yellow", exclude=pid)
                    self._log(f"{p.name} disconnected.")
                    if not self.game_started:
                        self._broadcast_lobby()
                if p.is_host:
                    p.is_host = False
                    self._reassign_host()
            return True

        if mtype != "input":
            return True

        p = self.players.get(pid)
        if p is None or not p.connected:
            return True

        text = str(msg.get("text", "")).strip()

        if p.pending == "name":
            if not text:
                self.send_text(p, "Name cannot be empty. Enter your name:", "red")
                return True
            text = text[:20]

            # Reconnection: someone who was mid-game and dropped can rejoin
            # under the same name and resume their seat (role, alive state).
            reconnect_target = next(
                (pl for pl in self.players.values()
                 if pl.id != pid and not pl.connected and pl.role is not None
                 and pl.name and pl.name.lower() == text.lower()),
                None,
            )
            if reconnect_target:
                old_id = reconnect_target.id
                p.name = reconnect_target.name
                p.role = reconnect_target.role
                p.alive = reconnect_target.alive
                p.spectator = False
                p.pending = None
                del self.players[old_id]
                self.send_text(p, f"Welcome back, {p.name}! You reconnected as {p.role}.", "green")
                self.send_text(p, roles.DESCRIPTIONS[p.role], "magenta")
                if not p.alive:
                    self.send_text(p, "You were eliminated before you dropped - you're watching as a spectator.", "yellow")
                self.broadcast_text(f"{p.name} has reconnected.", "green", exclude=pid)
                self._log(f"{p.name} reconnected.")
                return True

            if any(pl.name == text for pl in self.players.values() if pl.id != pid and pl.name):
                self.send_text(p, "That name is taken. Enter a different name:", "red")
                return True
            p.name = text
            p.pending = None
            self._log(f"{p.name} joined." + (" (spectator)" if p.spectator else ""))
            if p.spectator:
                self.send_text(p, f"You are watching as a spectator, {p.name}. Your chat is only visible to other spectators/eliminated players.", "yellow")
            else:
                if self.host_id is None:
                    self.host_id = pid
                    p.is_host = True
                if not self.game_started:
                    self._broadcast_lobby()
                    if p.is_host:
                        self.send_text(p, f"You are the host. Type 'start' once at least {self.min_players} players have joined, or 'bots <N>' to fill the lobby with AI players.", "cyan")
            return True

        return False  # caller resolves: pending action, or free chat

    def _reassign_host(self):
        for p in self.players.values():
            if p.connected and p.name and not p.spectator:
                p.is_host = True
                self.host_id = p.id
                self.send_text(p, "You are now the host. Type 'start' when ready, or 'bots <N>' to fill the lobby with AI players.", "cyan")
                return
        self.host_id = None

    def _broadcast_lobby(self):
        names = [p.name for p in self.players.values() if p.connected and p.name and not p.spectator]
        for p in self.players.values():
            if p.connected and p.name and not p.spectator:
                self.send_to(p, {"type": "lobby", "players": names, "min_players": self.min_players})

    def _broadcast_chat(self, p, text):
        if not text:
            return
        is_ghost = p.spectator or not p.alive
        label = f"[spectator] {p.name}" if is_ghost else p.name
        for other in self.players.values():
            if not other.connected or not other.name:
                continue
            other_is_ghost = other.spectator or not other.alive
            if is_ghost and not other_is_ghost:
                continue  # the dead/spectators can't be heard by the living
            self.send_to(other, {"type": "chat", "from": label, "text": text})
        self._log(f"chat: {label}: {text}")

    def _resolve_target(self, text, options):
        """Returns (ok, target_or_None). ok=False means invalid input."""
        t = text.strip()
        if t.lower() in ("abstain", "skip"):
            return True, None
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(options):
                return True, options[idx]
            return False, None
        for o in options:
            if o.name.lower() == t.lower():
                return True, o
        return False, None

    def _prompt(self, p, kind, options, text, time_limit):
        p.pending = "action"
        p.pending_kind = kind
        p.pending_options = options
        opts = [{"num": i + 1, "name": o.name} for i, o in enumerate(options)]
        self.send_to(p, {"type": "prompt", "kind": kind, "options": opts, "text": text, "time_limit": time_limit})

    def _eliminate_with_last_words(self, victim, announce_text):
        """Kill victim and give them a short public last-words window if
        they're still connected. Their role stays hidden - it's only
        revealed for everyone at once on the final game-over screen.
        Shared by the day vote and the delayed infection resolution."""
        victim.alive = False
        self.broadcast_text(announce_text, "red")
        if victim.connected:
            self.send_text(victim, f"You have been eliminated. You have {self.LAST_WORDS_TIME} seconds for last words, seen by everyone:", "yellow")

            def on_last_words(pid, msg):
                mtype = msg.get("type")
                consumed = self._handle_common(pid, msg)
                if mtype == "__disconnect__":
                    return pid == victim.id
                if consumed:
                    return False
                other = self.players.get(pid)
                if other is None:
                    return False
                text = str(msg.get("text", "")).strip()
                if other.id == victim.id:
                    if text:
                        self.broadcast_text(f"{victim.name} (last words): {text}", "magenta")
                    return True
                self._broadcast_chat(other, text)
                return False

            self._pump(time.time() + self.LAST_WORDS_TIME, on_last_words)

    def _resolve_pending_infection(self):
        """Applies whatever the Grad Student set in motion last night. It's
        one-turn-delayed: the target doesn't actually die until this point,
        one full night later."""
        if self.pending_infection_id is not None:
            victim = self.players.get(self.pending_infection_id)
            self.pending_infection_id = None
            if victim and victim.alive:
                self._eliminate_with_last_words(victim, f"{victim.name} never woke up this morning...")
                self._log(f"{victim.name}'s influence took hold overnight ({victim.role}).")

    def _pump(self, deadline, on_message):
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            try:
                pid, msg = self.inbound.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if on_message(pid, msg):
                return

    def _alive_players(self):
        return [p for p in self.players.values() if p.connected and p.name and not p.spectator and p.alive]

    def _all_named_active(self):
        return [p for p in self.players.values() if p.connected and p.name and not p.spectator]

    # ------------------------------------------------------------------ #
    # Game phases
    # ------------------------------------------------------------------ #
    def lobby_phase(self):
        print(f"[server] Listening on {self.host}:{self.port} - waiting for players (min {self.min_players})...")
        while True:
            pid, msg = self.inbound.get()
            if self._handle_common(pid, msg):
                continue
            p = self.players.get(pid)
            if p is None or p.spectator:
                continue
            text = str(msg.get("text", "")).strip()
            lowered = text.lower()
            if p.is_host and lowered == "start":
                active = self._all_named_active()
                if len(active) < self.min_players:
                    self.send_text(p, f"Need at least {self.min_players} players to start (currently {len(active)}).", "red")
                else:
                    self.game_started = True
                    self._log(f"Game started with {len(active)} players: " + ", ".join(x.name for x in active))
                    return
            elif p.is_host and (lowered == "bots" or lowered.startswith("bots ")):
                arg = text[len("bots"):].strip()
                if not arg.isdigit() or not (1 <= int(arg) <= self.MAX_BOTS_PER_REQUEST):
                    self.send_text(p, f"Usage: 'bots <N>' with N from 1 to {self.MAX_BOTS_PER_REQUEST}.", "red")
                else:
                    n = int(arg)
                    error = self.spawn_bots(n)
                    if error:
                        self.send_text(p, f"Couldn't add bots: {error}", "red")
                    else:
                        self.send_text(p, f"Adding {n} bot{'s' if n != 1 else ''} to the lobby...", "cyan")
                        self._log(f"{p.name} added {n} bot(s) to the lobby.")
            else:
                self._broadcast_chat(p, text)

    def assign_roles(self):
        active = self._all_named_active()
        pool = roles.build_role_pool(len(active))
        random.shuffle(pool)
        for p, role in zip(active, pool):
            p.role = role
            p.alive = True

        for p in active:
            self.send_to(p, {
                "type": "role",
                "role": p.role,
                "description": roles.DESCRIPTIONS[p.role],
            })
        self.broadcast_text(f"\nRoles assigned. {len(active)} players in play. Let the game begin!", "bold")
        self._log("Role distribution: " + ", ".join(f"{p.name}={p.role}" for p in active))

    def night_phase(self):
        self.round += 1
        self.broadcast_phase("night", self.round)
        self.broadcast_text(f"\n=== Night {self.round} ===", "blue")

        self._resolve_pending_infection()
        if self.check_win():
            return

        alive = self._alive_players()
        grad_student = next((p for p in alive if p.role == roles.GRAD_STUDENT), None)
        mentor = next((p for p in alive if p.role == roles.MENTOR), None)
        warden = next((p for p in alive if p.role == roles.WARDEN), None)
        professors = [p for p in alive if p.role == roles.PROFESSOR]

        if grad_student:
            infect_targets = [p for p in alive if p.id != grad_student.id]
            self._prompt(grad_student, "infect", infect_targets, "Choose a student to influence:", self.NIGHT_TIME)
        if mentor:
            self._prompt(mentor, "save", alive, "Choose a player to protect:", self.NIGHT_TIME)
        if warden:
            room_targets = [p for p in alive if p.id != warden.id]
            self._prompt(warden, "inspect", room_targets, "Choose a player's room to check:", self.NIGHT_TIME)
        for prof in professors:
            self._prompt(prof, "steal", [p for p in alive if p.id != prof.id], "Choose a player to deduct points from:", self.NIGHT_TIME)

        actors = set()
        if grad_student:
            actors.add(grad_student.id)
        if mentor:
            actors.add(mentor.id)
        if warden:
            actors.add(warden.id)
        for prof in professors:
            actors.add(prof.id)
        for p in alive:
            if p.id not in actors:
                self.send_text(p, "Night falls. Other roles are making their move... sit tight.", "dim")

        infect_target = {"id": None}
        save_target = {"id": None}
        inspect_target = {"id": None}
        pending_pids = set(actors)

        def on_message(pid, msg):
            mtype = msg.get("type")
            consumed = self._handle_common(pid, msg)
            if mtype == "__disconnect__":
                pending_pids.discard(pid)
                return len(pending_pids) == 0
            if consumed:
                return len(pending_pids) == 0

            p = self.players.get(pid)
            if p is None:
                return len(pending_pids) == 0
            if p.pending != "action":
                # free chat from ghosts/idle alive players during the night
                text = str(msg.get("text", "")).strip()
                self._broadcast_chat(p, text)
                return len(pending_pids) == 0

            text = str(msg.get("text", "")).strip()
            ok, target = self._resolve_target(text, p.pending_options)
            if not ok:
                self.send_text(p, "Invalid choice. Enter a number/name from the list, or 'skip'.", "red")
                return len(pending_pids) == 0

            p.pending = None
            pending_pids.discard(pid)
            kind = p.pending_kind
            if kind == "infect":
                infect_target["id"] = target.id if target else None
            elif kind == "save":
                save_target["id"] = target.id if target else None
            elif kind == "inspect":
                inspect_target["id"] = target.id if target else None
            elif kind == "steal" and target:
                target.score -= 1
                p.score += 1
            return len(pending_pids) == 0

        self._pump(time.time() + self.NIGHT_TIME, on_message)
        for p in list(self.players.values()):
            if p.pending == "action":
                p.pending = None

        infect_id = infect_target["id"]
        saved_id = save_target["id"]
        if infect_id and infect_id != saved_id:
            # Delayed and silent: the target isn't told, and doesn't die
            # until _resolve_pending_infection() runs at the top of next night.
            self.pending_infection_id = infect_id
        elif infect_id and infect_id == saved_id and mentor:
            # Only the Mentor is told, and only when their pick actually
            # mattered - a pick that didn't match tonight's attack stays silent.
            self.send_text(mentor, "The student was saved!", "green")

        inspect_id = inspect_target["id"]
        if inspect_id and warden:
            inspected = self.players.get(inspect_id)
            # A room reads "missing" for any of three reasons, and the
            # Warden can't tell which: the occupant was tonight's attack
            # target, they ARE the Grad Student and went out to attack, or
            # they ARE the Mentor and went out to protect someone. All three
            # look identical - real information, but a genuinely ambiguous
            # one, not a direct accusation.
            missing = (
                (infect_id is not None and inspect_id == infect_id)
                or (grad_student is not None and infect_id is not None and inspect_id == grad_student.id)
                or (mentor is not None and saved_id is not None and inspect_id == mentor.id)
            )
            if missing:
                self.send_text(warden, f"{inspected.name} is missing from their room last night!", "red")
                # Revealed publicly next morning, feeding the normal day
                # vote - not an automatic removal like the old jail/expel.
                self.pending_suspicion_id = inspect_id
            else:
                self.send_text(warden, f"{inspected.name} is reported present in their room.", "cyan")

        self._log(f"Night {self.round} complete.")

    def day_phase(self):
        self.broadcast_text(f"\n=== Day {self.round} ===", "yellow")

        if self.pending_suspicion_id is not None:
            suspect = self.players.get(self.pending_suspicion_id)
            self.pending_suspicion_id = None
            if suspect and suspect.alive:
                self.broadcast_text(
                    f"[WARDEN'S REPORT] {suspect.name} was reported missing from their room "
                    "during last night's check. Vote wisely.",
                    "magenta",
                )

        if self.check_win():
            return

        self.broadcast_phase("day_discuss", self.round)
        self.broadcast_text(
            f"Discussion phase ({self.DAY_DISCUSS_TIME}s). Chat freely, or type "
            "'accuse <name>' to publicly flag a suspect on the suspicion board.",
            "cyan",
        )

        disc_alive_by_name = {p.name.lower(): p for p in self._alive_players()}
        accusations = {}  # accuser_id -> target_id, latest one counts

        def on_discuss(pid, msg):
            consumed = self._handle_common(pid, msg)
            if consumed:
                return False
            p = self.players.get(pid)
            if p is None:
                return False
            text = str(msg.get("text", "")).strip()
            lowered = text.lower()
            if p.alive and not p.spectator and (lowered.startswith("accuse ") or lowered.startswith("!accuse ")):
                target_name = text.split(" ", 1)[1].strip() if " " in text else ""
                target = disc_alive_by_name.get(target_name.lower())
                if target is None or target.id == p.id:
                    self.send_text(p, "Usage: accuse <living player's name> (not yourself).", "red")
                else:
                    accusations[p.id] = target.id
                    tally = Counter(accusations.values())
                    board = ", ".join(
                        f"{self.players[t].name}({c})" for t, c in tally.most_common() if t in self.players
                    )
                    self.broadcast_text(f"[ALERT] {p.name} publicly accuses {target.name}! Suspicion board: {board}", "magenta")
            else:
                self._broadcast_chat(p, text)
            return False

        self._pump(time.time() + self.DAY_DISCUSS_TIME, on_discuss)

        alive = self._alive_players()
        if len(alive) <= 1 or self.check_win():
            return

        self.broadcast_phase("vote", self.round)
        self.broadcast_text(f"Voting phase ({self.DAY_VOTE_TIME}s). Choose who to eliminate.", "magenta")
        for p in alive:
            self._prompt(p, "vote", alive, "Vote to eliminate a player (or 'skip' to abstain):", self.DAY_VOTE_TIME)

        votes = {}
        pending_pids = set(p.id for p in alive)

        def on_vote(pid, msg):
            mtype = msg.get("type")
            consumed = self._handle_common(pid, msg)
            if mtype == "__disconnect__":
                pending_pids.discard(pid)
                return len(pending_pids) == 0
            if consumed:
                return len(pending_pids) == 0

            p = self.players.get(pid)
            if p is None:
                return len(pending_pids) == 0
            if p.pending != "action":
                text = str(msg.get("text", "")).strip()
                self._broadcast_chat(p, text)
                return len(pending_pids) == 0

            text = str(msg.get("text", "")).strip()
            ok, target = self._resolve_target(text, p.pending_options)
            if not ok:
                self.send_text(p, "Invalid choice. Enter a number/name from the list, or 'skip'.", "red")
                return len(pending_pids) == 0

            p.pending = None
            pending_pids.discard(pid)
            if target:
                votes[pid] = target.id
            return len(pending_pids) == 0

        self._pump(time.time() + self.DAY_VOTE_TIME, on_vote)
        for p in list(self.players.values()):
            if p.pending == "action":
                p.pending = None

        vote_values = list(votes.values())
        if vote_values:
            tally = Counter(vote_values)
            top = max(tally.values())
            leaders = [pid for pid, count in tally.items() if count == top]
        else:
            leaders = []

        if len(leaders) == 1:
            eliminated_id = leaders[0]
            self._no_elim_streak = 0
        elif self._no_elim_streak >= 1:
            # The day vote can still stall out entirely (ties, all-skip),
            # so after a second straight tied/empty day, force a resolution
            # rather than let the game hang on discussion alone.
            pool = leaders if leaders else [p.id for p in alive]
            eliminated_id = random.choice(pool)
            self._no_elim_streak = 0
            self.broadcast_text("Two days straight with no decision - the tie is broken at random.", "magenta")
        else:
            self._no_elim_streak += 1
            self.broadcast_text("The vote is tied or inconclusive. No one is eliminated.", "yellow")
            self._log(f"Day {self.round}: no elimination (tie/no votes).")
            return

        victim = self.players.get(eliminated_id)
        if victim is None:
            # Target reconnected under a new id mid-phase and the old id was
            # retired; treat as if the vote fizzled rather than crash.
            self.broadcast_text("The accused is no longer in the game. No one is eliminated.", "yellow")
            self._log(f"Day {self.round}: vote target vanished (stale id).")
            return

        self._eliminate_with_last_words(victim, f"{victim.name} has been voted out!")
        self._log(f"Day {self.round}: {victim.name} eliminated ({victim.role}).")

    def check_win(self):
        alive = self._alive_players()
        grad_alive = [p for p in alive if p.role == roles.GRAD_STUDENT]
        good_alive = [p for p in alive if p.role != roles.GRAD_STUDENT]
        if not grad_alive:
            self._end_game("students")
            return True
        if len(grad_alive) >= len(good_alive):
            self._end_game("grad_student")
            return True
        return False

    def _end_game(self, winner):
        self.broadcast_phase("game_over")
        named = [p for p in self.players.values() if p.name and not p.spectator]
        role_list = {p.name: p.role for p in named}
        score_list = {p.name: p.score for p in named}
        # The "game_over" message below carries the same winner + role list and
        # is what every client renders as the final screen - broadcasting the
        # same information again as plain text would just show it twice.
        for p in self.players.values():
            self.send_to(p, {"type": "game_over", "winner": winner, "roles": role_list, "scores": score_list})
        self._log(f"GAME OVER - {winner} wins. Roles: {role_list}. Scores: {score_list}")
        self._write_match_log()

    def _write_match_log(self):
        os.makedirs("match_history", exist_ok=True)
        fname = os.path.join("match_history", f"match_{time.strftime('%Y%m%d_%H%M%S')}.log")
        with open(fname, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log))
        print(f"[server] Match log written to {fname}")
