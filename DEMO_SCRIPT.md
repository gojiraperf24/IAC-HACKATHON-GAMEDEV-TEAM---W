# Demo Video Checklist (3-5 minutes, multiple real people)

Goal per the judging rubric: show one **full play cycle** (discussion -> vote ->
elimination) live, with real people, and let the terminal UI carry the "wow."

## Before you hit record

- [ ] All players on the same WiFi/hotspot, OR all in the same room using
      separate terminal windows on one machine.
- [ ] Host runs `dist\terminal-mafia-server.exe --port 5050 --min-players 4`
      (swap in `python server.py ...` if running from source).
- [ ] Everyone else has `dist\terminal-mafia-client.exe <host-ip> 5050` ready
      to run the moment recording starts.
- [ ] Decide who's on camera/mic for reactions - the accusation board and
      last-words moments are the best "fun factor" beats to capture.

## Suggested shot list (~4 min)

1. **(0:00-0:30) Cold open** - show the server terminal starting up, then 2-4
   client terminals connecting side by side (split screen or multiple phones
   filming multiple screens). Let the banner + typing effect play out on at
   least one client - it's the most visually distinct moment.
2. **(0:30-1:00) Role reveal** - show one player's screen as their role comes
   in (ideally the Grad Student player, muted/whispering "oh no" for effect).
3. **(1:00-1:45) Night phase** - narrate what's happening off-screen (the
   Grad Student picking a target) while the other players' screens show
   "sit tight."
4. **(1:45-3:00) Day: discussion + accusation board** - this is the key
   original mechanic. Have 2+ players actually type `accuse <name>` on camera
   so the live suspicion tally updates and everyone reacts to it.
5. **(3:00-3:45) Vote + elimination + last words** - show the vote landing,
   the "last words" prompt, and the role reveal.
6. **(3:45-4:00) Win condition** - either let the game finish for real, or cut
   here with a quick voiceover: "the game continues until [win condition]."

## If you're short on players

Run `--bots N` to fill remaining seats, but keep the "multiple real people
playing" requirement satisfied by having at least 3-4 *real* participants
actively typing on camera - bots are for filling out numbers, not replacing
the humans the rubric explicitly asks for.

## Fallback if live LAN play glitches during the take

Everyone can play on **one machine** in separate terminal windows connecting
to `127.0.0.1` - functionally identical, and still satisfies "multiple
terminal windows on one machine" from the rulebook.
