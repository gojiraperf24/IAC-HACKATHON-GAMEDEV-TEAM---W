# Terminal Mafia

A local-hosted, multiplayer, terminal-based social deduction game (Mafia / Among Us
style) built for **ROOT 36 — IAC 8.0, IIT Palakkad**.

A campus-intrigue presentation skin on top of the standard Mafia mechanic: a
Grad Student is quietly picking off students one by one, while a Mentor and a
Warden try to stop them before everyone else runs out. The wire protocol and
core game loop are the same shape as classic Mafia — only the roles, phase
names, and flavor text are themed.

One player hosts a game server on their machine; everyone else connects from their
own terminal — either other windows on the same machine, or other devices on the
same LAN / mobile hotspot. No GUI, no cloud, no external services: pure sockets and
text.

## Requirements

- Python 3.9+ (standard library only — **no `pip install` needed** to play), **or**
  the prebuilt Windows executables in [`dist/`](dist/) if you don't have Python
- All players on the same local network (or the same machine, for a solo test)

## Quick start (prebuilt executables)

No Python required. From `dist/`:

```bash
dist\terminal-mafia-server.exe --port 5050
```

Everyone else:

```bash
dist\terminal-mafia-client.exe <host-ip> 5050
```

All three also work by double-clicking the `.exe` directly (no terminal
needed) - `terminal-mafia-server.exe` starts on the default port 5050, and
`terminal-mafia-client.exe` / `terminal-mafia-bot.exe` will try to find the
server automatically on the local network/hotspot, falling back to asking
for the host IP and port if nothing answers (some phone hotspots block
this kind of discovery).

(`terminal-mafia-bot.exe` is the AI bot, used automatically by `--bots N`.)
Rebuild them yourself anytime with `pip install pyinstaller` and
`python -m PyInstaller --onefile server.py` (same for `client.py` /
`bot_client.py`) — they're just packaged copies of the scripts below.

## Quick start (from source)

**1. Host starts the server** (pick any free port, e.g. 5050):

```bash
python server.py --port 5050
```

The server prints its own bind address. Find the host machine's LAN IP with
`ipconfig` (Windows) / `ifconfig` or `ip addr` (Mac/Linux) — look for something like
`192.168.x.x`.

**2. Everyone else connects** from their own terminal:

```bash
python client.py <host-ip> 5050
```

On the same machine, just open more terminal windows and connect to `127.0.0.1`
instead of a LAN IP.

**3. Enter a name when prompted.** The first player to join is the **host** and can
type `start` once at least 4 players (configurable) have joined.

**4. Play.** Prompts tell you exactly what to do each phase — type a number, a
player's name, or `skip`.

### Solo testing without other humans

The host can add AI bot players right from their own client window - once
you're the host, type `bots <N>` in the lobby (e.g. `bots 4`) to fill empty
seats without needing anyone else. No separate command or window required.

Bots react to what's actually happening rather than picking from a fixed
list every time - they respond when accused, comment on a Warden's report,
and lean toward accusing/voting for whoever a Warden flagged (treating it
as real evidence, not a certainty). All rule-based, no external services.

Alternatively, start the server with bots already attached from the CLI:

```bash
python server.py --port 5050 --bots 4
```

### Options

```
python server.py [--port 5050] [--host 0.0.0.0] [--min-players 4] [--bots 0]
```

## How to play

A campus intrigue reskin of the standard Mafia/Werewolf mechanic. Each night,
players with special roles secretly submit an action. Each day, everyone
discusses in an open chat, then votes to eliminate a suspect.

| Role | Team | Ability |
|---|---|---|
| **Grad Student** | Alone | Always exactly one. Each night, chooses another student to influence. The target isn't told - they quietly die at the start of the *following* night, unless the Mentor protects them that same night. Wins once their side reaches parity with everyone else remaining. |
| **Mentor** | Everyone else | Each night, freely chooses any player (including themselves) to protect from the Grad Student's influence. If the pick matches that night's attack, the Mentor is told "the student was saved" - otherwise, silence. Can't save someone already marked from a previous night. |
| **Warden** | Everyone else | Each night, checks one player's room. It comes back **missing** if that player was the attack target, *or* is the Grad Student who went out to attack, *or* is the Mentor who went out to protect someone - the Warden can't tell which. A missing report is announced publicly the next morning; otherwise the room is reported present. |
| **Professor** (7+ players only) | Everyone else | Each night, deduct a point from another player and add it to your own score. No effect on who's alive. |
| **Student** | Everyone else | No special ability - just a vote and your read on the room. |

Role counts scale with the player count: always exactly 1 Grad Student, 1
Mentor, 1 Warden; a Professor is added once there are 7+ players; everyone
else is a Student. Every player only ever sees information their own role
is entitled to - hidden state lives entirely on the server and is never sent
to clients that shouldn't see it.

**The Grad Student's influence doesn't kill instantly.** The target isn't
removed until the *following* night - the only immediate elimination is the
**day vote**. If a day vote ties or gets no votes two times in a row, the
tie is broken at random rather than letting the game stall forever.

**The Warden's report is evidence, not a verdict.** "Missing" has three
possible causes (the attack's target, the Grad Student, or the Mentor) and
the Warden can't distinguish them - a genuine clue, not a direct accusation.
It never removes anyone by itself; the community still has to act on it
through the normal day vote.

**Discussion isn't just a timer.** During the day, type `accuse <name>` to publicly
flag a suspect — it updates a live suspicion tally broadcast to the whole table,
on top of free-form chat.

**Last words.** A player eliminated (by day vote, or once a delayed influence
resolves) gets a short window to speak. Their role stays hidden - all roles
are revealed together only on the final game-over screen.

**Win conditions**

- **Everyone else wins** the moment the Grad Student has been eliminated.
- **The Grad Student wins** the moment everyone else remaining is down to
  one player or fewer.

Eliminated players become **spectators**: they keep receiving the live game
feed, but their chat is only visible to other spectators/eliminated players,
never to the living.

**Reconnecting.** If you drop mid-game, reconnect with `python client.py <host> <port>`
and enter the *exact same name* you had before — you'll resume your seat, role,
and alive/dead status instead of being locked out.

## Architecture

```
server.py         CLI entry point for the host: parses args, spawns bots, runs GameServer
client.py         Terminal UI for a human player: renders server messages, relays typed input
bot_client.py      Same wire protocol as client.py, but auto-plays for testing/demos
mafia/
  protocol.py     Newline-delimited JSON message framing shared by server & clients
  discovery.py    UDP broadcast/reply so the client can auto-find a server on the LAN
  roles.py        Pure role definitions + role-count distribution (no I/O, unit-testable)
  game.py         GameServer: connection handling + the night/day phase state machine
  colors.py       Dependency-free ANSI color helpers for the terminal UI
match_history/    One human-readable log file per completed match
```

**Networking model:** the server is authoritative. It accepts TCP connections and
spawns one lightweight reader thread per client; those threads only ever push
incoming messages onto a single thread-safe queue. All game-state mutation
(role assignment, phase transitions, vote tallying, win checks) happens on one
thread, so there's no locking to get wrong around the actual game logic. Every
role-specific prompt, private investigation result, and chat visibility rule is
resolved server-side — a client only ever receives what its role is allowed to
know.

**Resilience:** a disconnect at any point (lobby, night action, discussion, vote)
is caught and handled gracefully — the player is marked disconnected, the rest of
the table is notified, the win condition is re-checked, and if the disconnecting
player was the host, host status is transferred automatically. Invalid input
(bad menu numbers, unknown names) is rejected with a re-prompt instead of
crashing the server or blocking other players.

## Tests

`mafia/roles.py` is pure logic (no sockets/threads), so it's unit-tested
directly. There's also a live integration suite that spins up a real
`GameServer` on a loopback socket and throws malformed JSON, oversized
payloads, wrong-typed fields, unknown message types, and abrupt disconnects
at it — confirming a broken/hostile client can never take the game down for
everyone else.

```bash
python -m unittest discover tests -v
```

## AI usage

Generative AI assistance (Claude) was used during development for code
generation, in line with the ROOT 36 rule book's AI tool policy. All logic was
authored, tested, and adapted specifically for this project during the hackathon
window.

## Known limitations

- No GUI/animations — colored ANSI text only, by design (CLI-only requirement).
- Timed phases use fixed durations (`mafia/game.py`); tune `NIGHT_TIME`,
  `DAY_DISCUSS_TIME`, `DAY_VOTE_TIME`, `LAST_WORDS_TIME` for a faster or
  slower table.
- The client pauses briefly (`READ_DELAY` in `client.py`) after each chat/
  text line so a burst of messages doesn't flash by unreadably fast — prompts
  themselves are never delayed.
