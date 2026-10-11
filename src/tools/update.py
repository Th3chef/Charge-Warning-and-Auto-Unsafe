"""After a game patch: checks whether the game's sounds for any weapon the mod covers changed (the RS-422 Railgun's
content/audio/wep_railgun, the PLAS-45 Epoch's content/audio/wep_plasma_blaster) and, if one did, rebuilds the mod on
top of the new sounds.

    python update.py --filediver <filediver executable> --gamedir <Helldivers 2 folder, the one containing 'data'>
                     [--version 3.0.1]

1. Asks Filediver where each weapon's bank lives in the game (ignoring mod patch files) and extracts the game's own
   bank and dep.
2. Compares each bank and dep with the ones the current release was built from (../game/built_from.json).
   All the same -> "no update needed" (exit 0): the released mod keeps working as is.
   Any changed  -> copies both weapons' new banks and deps to the build's game folder (../game/, or RCW_GAME_DIR as for
                   build.py), rebuilds with build.py (every hook is found again by discover.py, and verify.py checks the
                   zips) and lists what moved (exit 2): test it in game, then release it.
Exit 1 means something needs a person: Filediver failed, or a bank changed so much its hooks were not found."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build                                        # ((3.0.1 review) one game folder: build.GAME, RCW_GAME_DIR included)
GAME = build.GAME


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
    # ((3.0.1 review) the game's own archive is the one that is not a patch file (every mod is a .patch_N), and there
    # must be exactly one)
    vanilla = [x for x in archives if '.patch_' not in x]
    if len(vanilla) != 1:
        return ('only mod copies of %s were found: %s' if not vanilla else
                '%s is in more than one game archive (%s): it needs a look') % (name, archives)
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

    old = old_stamps()
    changed, extracted = [], []
    tmp = tempfile.mkdtemp()
    try:
        for w in build.WEAPONS:
            got = extract(a.filediver, a.gamedir, w['bank'], tmp)
            if isinstance(got, str):
                print(got); return 1
            extracted += got
            # ((3.0.1 review) the dep is compared too: it ships in the patch next to the bank)
            new = {k: hashlib.md5(open(f, 'rb').read()).hexdigest() for k, f in zip(('game_bank_md5', 'game_dep_md5'), got)}
            was = old.get(w['bank'], {})
            diff = [k for k in new if was.get(k) != new[k]]
            if not diff:
                print('%s: the game\'s sounds are unchanged (bank %s, dep %s).' % (
                    w['title'], new['game_bank_md5'][:12], new['game_dep_md5'][:12]))
                continue
            print('%s: the game\'s sounds changed (%s).' % (w['title'], ', '.join(
                '%s was %s, now %s' % (k.split('_')[1], (was.get(k) or '?')[:12], new[k][:12]) for k in diff)))
            changed.append(w)
        if not changed:
            print('No update needed: the released mod matches the game.'); return 0
        # ((3.0.1 review) the build reads both weapons' banks and deps: copy them all, not just the changed ones, so it
        # never mixes the new game's files with stale copies)
        os.makedirs(GAME, exist_ok=True)
        for f in extracted:
            shutil.copy(f, os.path.join(GAME, os.path.basename(f)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

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
                 if k not in ('game_bank_md5', 'game_dep_md5') and k in before and before[k] != v]
        print('%s: %s' % (w['title'], ('moved: ' + '; '.join(moved)) if moved else 'every hook is where it was'))
    print('Rebuilt. Test it in game, then release it as an update.')
    return 2


if __name__ == '__main__':
    sys.exit(main())
