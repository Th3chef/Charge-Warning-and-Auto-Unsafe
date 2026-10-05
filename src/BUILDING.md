# Railgun Warning & Auto Unsafe - source (formerly Railgun Overcharge Warning)

Builds the mod from the game's own railgun sound bank. Nothing in here comes from another mod.

    tools/sound.py   the warning sound (synthesised; writes assets/warning.wav, the released take, and
                     assets/warning.json, the cue: when the first warning beep starts inside the sound)
    tools/art.py     thumbnail, Nexus header, gallery, GitHub social preview and Arsenal option icons, drawn from the
                     sound and its cue (Playwright Chromium, Anton + Barlow Condensed in art/fonts)
    tools/wwise_bank.py  small reader/writer for the game's Wwise banks
    tools/build.py   adds the warning to the bank and writes build/Railgun-Warning-and-Auto-Unsafe-<ver>.zip
    tools/discover.py  finds the charge events, charge value and mixer in any version of the game's bank
    tools/update.py  after a game patch: re-extracts the bank and rebuilds only if the railgun audio changed
    tools/auto_unsafe.lua  the "Auto unsafe mode" option: a Bingus Shared Loader Lua addon (build.py fills in the version)

## How it works
The game's railgun bank (content/audio/wep_railgun) gets one new sound, one Play and two Stop actions:
- Play on the charge-start event, delayed so the sound's cue (the first piezo warning beep) starts 2.5 s into the
  charge (90%, full damage); the beeps run for 0.32 s and end in a discharge snap.
- Its volume follows the game's railgun charge value (RTPC 0xBFDCF9F2, 0..1): silent up to 0.75, full from 0.76.
  Safe mode holds the charge at about 0.70, so safe mode stays silent.
- Stopped on the charge-end event and on the fire event.

## Auto unsafe mode option
A Lua addon in the option folder "Auto Unsafe" (needs Bingus Shared Loader). Every 0.25 s it looks up your helldiver's
support weapon (equipment record +8); a Railgun it hasn't seen yet in Safe gets Unsafe written once into the weapon
component's mode entry (weapon manager +96, 12 bytes per weapon: +0 fire mode 5 Safe / 6 Unsafe, +5 flag 16 in
Unsafe) and into the record's copy (+24, which the game refreshes from the entry every frame). All game addresses
come from code-pattern scans at start-up (remembered per game build in %LOCALAPPDATA%\RailgunAutoUnsafe.cache; every
cached spot is re-checked against its pattern, otherwise a full rescan); the entry must match the copy and all three
write targets must be writable before anything is written, else it does nothing. A weapon only counts as a Railgun when
its entity type in the game's owner table is the RS-422 Railgun's (resource hash 2e9d0bdc48b09e60) and that row is marked
as ours: the Arc Thrower uses the same fire mode numbers (2.0.0 switched it to unsafe and it blew up). Log: RailgunAutoUnsafe.log in the Bingus Logs folder (numbered test builds: Logs\test).
    python build.py            release + -Tester.zip (extra log lines, test GUID)
    python build.py test N     numbered test build

## Volume option
build.py writes one full patch per level in VOLUME_LEVELS (Volume/Loud, Medium, Quiet) and an Arsenal
"Warning volume" option with pick-one SubOptions; the levels differ only in the Sound's voice volume (prop 0x05,
VOICE_VOLUME_DB + offset). art.py draws the option icons (art/options).

## After a game patch (one command)
The mod has to ship the whole railgun sound bank (that is how the game loads audio), so when a patch changes the
railgun's audio the released mod still works but carries the older railgun sounds. To catch up:

    cd tools
    python update.py --filediver <path to filediver> --gamedir <Helldivers 2 folder that contains "data">

- Unchanged railgun audio: it says "no update needed" and does nothing.
- Changed: it extracts the game's new bank, re-finds everything the mod hooks into (tools/discover.py: the charge
  event, the charge-end event, the charge value, the mixer, the bank id - by what they do, not by fixed ids),
  rebuilds build/Railgun-Warning-and-Auto-Unsafe-<ver>.zip and lists anything that moved. Test it, then upload it.
  `--version 2.0.1` sets the new version number.
- It stops with a message if the bank changed too much to hook automatically (or the Wwise version changed).

What the mod adds is purely additive (one sound, one Play and two Stop actions appended to existing events), so
it never edits or removes anything the game has; an outdated copy only lacks the game's newest railgun sounds.
Retune by hand only if the game changes the charge itself: END_AT_S (2.5 s to 90%) and SILENT_UP_TO / FULL_FROM
(the charge value safe mode stays under) at the top of build.py.

## Building by hand
    cd tools && python sound.py && python art.py && python build.py
The game bank goes in game/ (update.py fetches it; or extract content/audio/wep_railgun.wwise_* with Filediver
using --audio-format raw --raw-format separate). game/built_from.json records which game bank the build used.

Needs: python 3 (build/update: standard library only; sound.py: numpy, scipy, pyloudnorm; art.py: pillow, playwright).
