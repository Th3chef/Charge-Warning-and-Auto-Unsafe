"""After a game patch: checks whether the game's railgun audio changed and, if it did, rebuilds the mod on top of it.

    python update.py --filediver <filediver executable> --gamedir <Helldivers 2 folder, the one containing 'data'>
                     [--version 1.0.1]

1. Asks Filediver where content/audio/wep_railgun lives in the game (ignoring mod patch files) and extracts the
   game's own bank and dep into ../game/.
2. Compares it with the bank the current release was built from (../game/built_from.json).
   Same bank  -> "no update needed" (exit 0): the released mod keeps working as is.
   New bank   -> rebuilds with build.py (the hooks are re-found by discover.py) and prints what moved (exit 2):
                 test it in game, then release it as an update.
Exit 1 means something needs a person: Filediver failed, or the bank changed so much the hooks were not found."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(os.path.dirname(HERE), 'game')
BANK = 'content/audio/wep_railgun.wwise_bank'


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--filediver', required=True)
    ap.add_argument('--gamedir', required=True)
    ap.add_argument('--version')
    a = ap.parse_args()

    code, out = run([a.filediver, '--gamedir', a.gamedir, '-l', '-i', BANK])
    m = re.search(re.escape(BANK) + r'.*?<-\s*(.+)', out)
    if not m:
        print('Filediver did not list the railgun bank:\n' + out[-2000:]); return 1
    archives = [x.strip() for x in m.group(1).split(',')]
    vanilla = [x for x in archives if not x.startswith('9ba626afa44a3aa3')]    # mod patches all use this archive name
    if not vanilla:
        print('only mod copies of the railgun bank were found: %s' % archives); return 1

    tmp = tempfile.mkdtemp()
    try:
        code, out = run([a.filediver, '--gamedir', a.gamedir, '-a', vanilla[0], '-i', 'content/audio/wep_railgun.wwise_*',
                         '--audio-format', 'raw', '--raw-format', 'separate', '-o', tmp])
        src = os.path.join(tmp, 'content', 'audio')
        files = ['wep_railgun.wwise_bank.main', 'wep_railgun.wwise_dep.main']
        if not all(os.path.exists(os.path.join(src, f)) for f in files):
            print('extraction failed:\n' + out[-2000:]); return 1
        new_md5 = hashlib.md5(open(os.path.join(src, files[0]), 'rb').read()).hexdigest()
        stamp_path = os.path.join(GAME, 'built_from.json')
        old = json.load(open(stamp_path)) if os.path.exists(stamp_path) else {}
        if old.get('game_bank_md5') == new_md5:
            print('The game\'s railgun audio is unchanged (bank %s): no update needed.' % new_md5[:12]); return 0
        os.makedirs(GAME, exist_ok=True)
        for f in files:
            shutil.copy(os.path.join(src, f), os.path.join(GAME, f))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('The game\'s railgun audio changed (was %s, now %s): rebuilding.' % (old.get('game_bank_md5', '?')[:12], new_md5[:12]))
    sys.path.insert(0, HERE)
    import build
    if a.version:
        build.VERSION = a.version
    try:
        build.main()
    except AssertionError as e:
        print('The rebuild stopped: %s\nThe bank changed too much for the automatic hooks; it needs a look.' % e); return 1
    print('Rebuilt. Test it in game, then release it as an update.')
    return 2


if __name__ == '__main__':
    sys.exit(main())
