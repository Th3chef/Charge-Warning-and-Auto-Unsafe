"""After a game patch: checks whether the game's sounds for any weapon the mod covers changed (the RS-422 Railgun's
content/audio/wep_railgun, the PLAS-45 Epoch's content/audio/wep_plasma_blaster) and, if one did, rebuilds the mod on
top of the new sounds.

    python update.py --filediver <filediver executable> --gamedir <Helldivers 2 folder, the one containing 'data'>
                     [--version 3.0.1]

1. Asks Filediver where each weapon's bank lives in the game (ignoring mod patch files) and extracts the game's own
   bank and dep.
2. Compares each with the bank the current release was built from (../game/built_from.json).
   All the same -> "no update needed" (exit 0): the released mod keeps working as is.
   Any changed  -> copies the new banks to ../game/, rebuilds with build.py (every hook is found again by discover.py,
                   and verify.py checks the zips) and lists what moved (exit 2): test it in game, then release it.
Exit 1 means something needs a person: Filediver failed, or a bank changed so much its hooks were not found."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(os.path.dirname(HERE), 'game')
sys.path.insert(0, HERE)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def old_stamps():
    """built_from.json: {version, weapons: {bank: stamp}} (3.0.0+); 2.x stamps held only the railgun bank."""
    path = os.path.join(GAME, 'built_from.json')
    if not os.path.exists(path):
        return {}
    data = json.load(open(path))
    if 'weapons' in data:
        return data['weapons']
    return {'wep_railgun': data}


def extract(filediver, gamedir, bank, tmp):
    """The game's own bank + dep for content/audio/<bank>, or an error message."""
    name = 'content/audio/%s.wwise_bank' % bank
    code, out = run([filediver, '--gamedir', gamedir, '-l', '-i', name])
    m = re.search(re.escape(name) + r'.*?<-\s*(.+)', out)
    if not m:
        return 'Filediver did not list %s:\n%s' % (name, out[-2000:])
    archives = [x.strip() for x in m.group(1).split(',')]
    vanilla = [x for x in archives if not x.startswith('9ba626afa44a3aa3')]    # mod patches all use this archive name
    if not vanilla:
        return 'only mod copies of %s were found: %s' % (name, archives)
    dest = os.path.join(tmp, bank)
    code, out = run([filediver, '--gamedir', gamedir, '-a', vanilla[0], '-i', 'content/audio/%s.wwise_*' % bank,
                     '--audio-format', 'raw', '--raw-format', 'separate', '-o', dest])
    src = os.path.join(dest, 'content', 'audio')
    files = [bank + '.wwise_bank.main', bank + '.wwise_dep.main']
    if not all(os.path.exists(os.path.join(src, f)) for f in files):
        return 'extraction of %s failed:\n%s' % (bank, out[-2000:])
    return [os.path.join(src, f) for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filediver', required=True)
    ap.add_argument('--gamedir', required=True)
    ap.add_argument('--version')
    a = ap.parse_args()

    import build
    old = old_stamps()
    changed = []
    tmp = tempfile.mkdtemp()
    try:
        for w in build.WEAPONS:
            got = extract(a.filediver, a.gamedir, w['bank'], tmp)
            if isinstance(got, str):
                print(got); return 1
            new_md5 = hashlib.md5(open(got[0], 'rb').read()).hexdigest()
            was = old.get(w['bank'], {}).get('game_bank_md5')
            if was == new_md5:
                print('%s: the game\'s sounds are unchanged (bank %s).' % (w['title'], new_md5[:12]))
                continue
            print('%s: the game\'s sounds changed (was %s, now %s).' % (w['title'], (was or '?')[:12], new_md5[:12]))
            changed.append(w)
            os.makedirs(GAME, exist_ok=True)
            for f in got:
                shutil.copy(f, os.path.join(GAME, os.path.basename(f)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not changed:
        print('No update needed: the released mod matches the game.'); return 0

    if a.version:
        build.VERSION = a.version
    try:
        build.main()
    except (Exception, SystemExit) as e:          # (a hook not found, a bank it can't read, a failed verify.py check)
        print('The rebuild stopped: %s: %s\nA bank changed too much for the automatic hooks; it needs a look.'
              % (type(e).__name__, e)); return 1
    new = old_stamps()
    for w in changed:
        before, after = old.get(w['bank'], {}), new.get(w['bank'], {})
        moved = ['%s %s -> %s' % (k, before.get(k), v) for k, v in after.items()
                 if k != 'game_bank_md5' and k in before and before[k] != v]
        print('%s: %s' % (w['title'], ('moved: ' + '; '.join(moved)) if moved else 'every hook is where it was'))
    print('Rebuilt. Test it in game, then release it as an update.')
    return 2


if __name__ == '__main__':
    sys.exit(main())
