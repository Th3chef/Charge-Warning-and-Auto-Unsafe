# Charge Warning & Auto Unsafe - source (formerly Railgun Warning & Auto Unsafe / Railgun Overcharge Warning)

Builds the mod from the game's own weapon sound banks (RS-422 Railgun and PLAS-45 Epoch). Nothing in here comes from
another mod.

    tools/sound.py     the warning sound (synthesized; writes assets/warning.wav, the released take, and
                       assets/warning.json, the cue: when the first warning beep starts inside the sound)
    tools/art.py       thumbnail, Nexus header, gallery, GitHub social preview and Arsenal option icons, drawn from the
                       sound and its cue (Playwright Chromium, Anton + Barlow Condensed in art/fonts)
    tools/wwise_bank.py  small reader/writer for the game's Wwise banks
    tools/build.py     adds a warning to each weapon's bank and writes build/Charge-Warning-and-Auto-Unsafe-<ver>.zip
    tools/discover.py  finds each bank's charge event, release event, shot event, charge value and mixer by what
                       they do (any game version)
    tools/verify.py    offline check of a built zip against the game banks (build.py runs it on every zip)
    tools/update.py    after a game patch: re-extracts both banks and deps and rebuilds only if a weapon's audio changed
    tools/auto_unsafe.lua  the "Auto unsafe mode" option: a Bingus Shared Loader Lua addon (build.py fills in the version)

## The weapons (build.py WEAPONS)
| weapon | bank | first beep | volume gate (charge value) | new object ids |
|---|---|---|---|---|
| RS-422 Railgun | content/audio/wep_railgun | 2.5 s (90%, full damage in unsafe mode) | silent to 0.75, full from 0.76 (safe mode holds ~0.70) | chef_railgun_charge_warning_* |
| PLAS-45 Epoch | content/audio/wep_plasma_blaster | 2.6 s (full charge, 2x damage; overloads at 3.25 s) | silent to 0.55, full from 0.57 (a safety gate only) | chef_epoch_charge_warning_* |

Both banks use the same charge value (RTPC 0xBFDCF9F2, 0..1). Each bank gets one new sound, one Play on the
charge event (delayed so the sound's cue lands on the first-beep time) and Stops on the release event, the shot event
(found by its name, wep_<bank>_fire) and any other event that cuts the charge sounds (the Epoch has one).
Retune by hand only if the game changes a weapon's charge: end_at_s and the gate in WEAPONS.

## Auto unsafe mode option
A Lua addon in the option folder "Auto Unsafe" (Bingus Shared Loader v19 or newer; older loaders still work). Every
0.25 s it reads your helldiver's support weapon from its loadout slot (the slot's address is found through your
owner row and loadout and re-checked every 2 s or when your helldiver changes); a Railgun it hasn't seen yet in Safe
gets Unsafe written once into the weapon component's mode entry (weapon manager +96, 12 bytes per weapon: +0 fire
mode 5 Safe / 6 Unsafe, +5 flag 16 in Unsafe) and into the record's copy (+24, which the game refreshes from the
entry every frame). A weapon only counts as a Railgun when its entity type in the game's owner table (its row count
is read from the game's code too) is the RS-422 Railgun's (resource hash 2e9d0bdc48b09e60) and that row is marked as
ours: the Arc Thrower and the Epoch use the same fire mode numbers. All game addresses come from code-pattern scans
(with v19: once every addon has loaded, via after_startup), remembered per game build in
%LOCALAPPDATA%\RailgunAutoUnsafe.cache (every cached spot is re-checked against its pattern, otherwise a full
rescan). The entry must match the copy and all three write targets must be writable before anything is written, and
if a write still fails, whatever was already written is put back. Log: RailgunAutoUnsafe.log in the loader's log
folder (numbered test builds: Logs\test).
    python build.py            release + -Tester.zip (extra log lines, test GUID)
    python build.py test N     numbered test build

## Volume options
Each weapon has its own Arsenal option (on/off) with pick-one SubOptions Loud / Medium / Quiet (folders
<Weapon>/<level>); the levels differ only in the Sound's voice volume (prop 0x05, VOICE_VOLUME_DB + offset). Each
level ships a full copy of that weapon's bank, because that is how the game loads audio.

## After a game patch (one command)
    cd tools
    python update.py --filediver <path to filediver> --gamedir <Helldivers 2 folder that contains "data">

- Unchanged audio for both weapons (bank and dep): "no update needed" (exit 0).
- A weapon's audio changed: it extracts the game's new bank(s), re-finds every hook by what it does, rebuilds
  build/Charge-Warning-and-Auto-Unsafe-<ver>.zip (checked by verify.py) and lists anything that moved (exit 2).
  `--version 3.0.1` sets the new version number.
- Exit 1: Filediver failed, or a bank changed too much to hook automatically (or the Wwise version changed).

What the mod adds is purely additive (one sound and its Play/Stop actions appended to existing events), so it never
edits or removes anything the game has; an outdated copy only lacks the game's newest sounds for that weapon.

## Building by hand
    cd tools && python sound.py && python art.py && python build.py
The game banks go in game/ (update.py fetches them; or extract content/audio/wep_railgun.wwise_* and
content/audio/wep_plasma_blaster.wwise_* with Filediver using --audio-format raw --raw-format separate).
game/built_from.json records which game banks and deps the build used (md5) and every hook it found. Set RCW_GAME_DIR
to use another folder for the game files (build.py and update.py both follow it). The zips are byte-reproducible: the
same game files, assets and art give the same zip, byte for byte.

Needs: python 3 (build/update/verify: standard library only; sound.py: numpy, scipy, pyloudnorm; art.py: pillow,
numpy, playwright).
