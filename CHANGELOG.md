# Changelog

## 3.0.0
- Renamed to Charge Warning & Auto Unsafe: it now covers the PLAS-45 Epoch too.
- New: Epoch warning - the same surge and warning beeps, starting exactly at full charge (2x damage), before it overloads. Its own option in your mod manager: on/off and Loud, Medium or Quiet.
- The Railgun warning is its own option now too (on/off and Loud, Medium or Quiet). If you update from 2.x, check its volume once: it may be back on Loud.
- Auto unsafe mode: requires Bingus Shared Loader v19 or newer (it uses the loader's log folder and scans once every mod has loaded; older loaders still work), checks your weapon with about 70% fewer memory reads, names the Epoch in its log and leaves it alone, and the log's start time is fixed.
- New art.
- Bigger download (about 26 MB): each volume level carries its own copy of each weapon's sounds.

## 2.0.1
- Fixed: Auto unsafe mode switched the ARC-3 Arc Thrower to "unsafe" too, which made it overload and explode at full charge. It now checks the weapon's type and only ever touches the RS-422 Railgun; every other weapon is left alone.
- Safer: it only acts on a weapon the game marks as yours, and checks that everything it needs to change can be changed before it changes anything.
- Faster start-up: what it finds in the game's code is remembered per game version (re-checked every launch, found again by itself after a game patch).
- The warning sound and the volume options are unchanged.

## 2.0.0
- Renamed to Railgun Warning & Auto Unsafe (it does both now).
- New warning sound: a growling electric surge with building crackle, fast piezo warning beeps and a discharge snap (replaces the coil-charge sound).
- New timing: the beeps start exactly at 90% charge (full damage). Fire on the beeps.
- Mixed to stay clear over the Railgun's own charge-up rumble.
- New option: Auto unsafe mode - every new Railgun starts in Unsafe (needs Bingus Shared Loader).
- New art.

## 1.1.0
- New Warning volume option in your mod manager: Loud (default, the same level as 1.0.1), Medium (-8 dB) or Quiet (-16 dB).
- Bigger download (about 13 MB): each volume level carries its own copy of the Railgun's sounds.

## 1.0.1
- Patch-proofed: the mod only adds to the Railgun's own sounds and never changes or removes anything the game has, so it keeps working after game patches, and an update after a patch is a quick rebuild on the new sounds.

## 1.0.0
- First release.
