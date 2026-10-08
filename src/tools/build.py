"""Builds Charge Warning & Auto Unsafe (formerly Railgun Warning & Auto Unsafe, before that Railgun Overcharge Warning)
from the game's own weapon sound banks: the RS-422 Railgun's and (from 3.0.0) the PLAS-45 Epoch's charge warnings.

Inputs (../game/, extracted from the game with Filediver, see README.md):
    wep_railgun.wwise_bank.main, wep_railgun.wwise_dep.main   the game's content/audio/wep_railgun (RS-422 Railgun)
    wep_plasma_blaster.wwise_bank.main, ...wwise_dep.main     the game's content/audio/wep_plasma_blaster (PLAS-45 Epoch)
    game_ids.txt (optional)                                    every object/audio id in the game's banks, for a clash check
    ../assets/warning.wav                                      the warning sound (sound.py)
    ../art/thumbnail_512.png, ../art/options/*.png             Arsenal icons (art.py)
    auto_unsafe.lua                                            the "Auto unsafe mode" option (a Bingus Shared Loader addon)
Output: ../build/<zip>, ready for Arsenal / the HD2 mod manager.
    python build.py            release
    python build.py test N     test build N: "<version> Test N", its own GUID (installs next to the release), tester logging
Every zip is checked with verify.py before the build finishes; a failed check deletes it and stops the build."""
import json, os, struct, sys, wave, zipfile
import hashlib
import wwise_bank as wb
from discover import discover

NAME = 'Charge Warning & Auto Unsafe'
FILE_BASE = 'Charge-Warning-and-Auto-Unsafe'      # zip names (no '&': Nexus file names allow only letters, digits, spaces and _ ' ( ) . -)
VERSION = '3.0.0'
GUID = 'c8736b4d-7681-43b3-ac5e-03314f2d7034'
GUID_TEST = '6cf144dc-0353-4f83-9da1-b57f2875bce7'   # test builds
TEST = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == 'test' else 0
DESCRIPTION = ('Charge warnings for the RS-422 Railgun (unsafe mode) and the PLAS-45 Epoch: a growling electric surge with '
               'fast warning beeps that start exactly when the charge does full damage (Railgun 90%, Epoch full charge), so '
               'you know when to fire before it overloads. Silent on quick shots, and it stops the moment you fire or let go. '
               'Option: Auto unsafe mode - every new Railgun you pick up starts in Unsafe (needs Bingus Shared Loader v19 or newer).')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.environ.get('RCW_GAME_DIR', os.path.join(ROOT, 'game'))   # where the extracted game banks live

# ---- what the mod hooks into (charge event, charge-end event, charge value, mixer...) is found in the game's
#      bank by discover.py each build, so a patched bank only needs re-extracting and rebuilding (update.py).
VOICE_VOLUME_DB = 10.0      # prop 0x05 = voice volume in dB (the railgun's charge whine uses +4); the "Loud" level

# ---- each weapon's Arsenal option: on/off, plus one pick-one sub-option per level (dB added to VOICE_VOLUME_DB);
#      first = default. Arsenal drops an option whose Include is an empty list, so the option carries no Include key.
VOLUME_LEVELS = [
    ('Loud', 0, 'Full volume: clearly audible over the charge-up.', 'vol_3'),
    ('Medium (-8 dB)', -8, 'Noticeably quieter than Loud.', 'vol_2'),
    ('Quiet (-16 dB)', -16, 'A subtle cue, well below Loud.', 'vol_1'),
]

# ---- behaviour, per weapon (retune only if the game changes that weapon's charge):
#      end_at_s      seconds into the charge where the sound's cue (the first warning beep) must land
#      silent_up_to / full_from   the warning's volume follows the game's charge value (RTPC 0..1): a safety gate
WEAPONS = [
    dict(key='railgun', bank='wep_railgun', title='RS-422 Railgun', folder='Railgun', id_prefix='chef_railgun_charge_warning_',
         end_at_s=2.5,                    # an unsafe charge reaches 90% (full damage) 2.5 s in
         silent_up_to=0.75, full_from=0.76,   # safe mode holds the charge at about 0.70, so safe mode stays silent
         option='Railgun warning', icon='railgun',
         blurb='The warning for the RS-422 Railgun in unsafe mode: beeps exactly at 90% charge (full damage). Silent in '
               'safe mode. Untick to turn it off; pick how loud it plays.'),
    dict(key='epoch', bank='wep_plasma_blaster', title='PLAS-45 Epoch', folder='Epoch', id_prefix='chef_epoch_charge_warning_',
         end_at_s=2.6,                    # full charge (2.0x damage) 2.6 s in; it overloads at 3.25 s (wiki, Oct 2026)
         silent_up_to=0.55, full_from=0.57,   # open well before the sound starts (1.99 s), whatever the value's scale
         option='Epoch warning', icon='epoch',
         blurb='The warning for the PLAS-45 Epoch: beeps exactly at full charge (2.0x damage), before it overloads. '
               'Untick to turn it off; pick how loud it plays.'),
]
STOP_FADE_MS = 100

# ---- Arsenal "Auto unsafe mode" option: a Bingus Shared Loader Lua addon in its own folder (on by default)
AUTO_UNSAFE_DIR = 'Auto Unsafe'
AUTO_UNSAFE_MODULE = 'mods/chef/railgun_auto_unsafe'
LUA_TYPE = 0xA14E8DFA2CD117E2

ARCHIVE = '9ba626afa44a3aa3.patch_0'
T_BANK, T_DEP = 0x535A7BD3E650D799, 0xAF32095C82F2B070
# engine metadata bytes 12..72 of the patch header. Audio patches need this exact block: every working audio mod
# checked (9 of them, several authors) carries it, and a sound bank patch with the material-mod header loads but
# stays silent.
HEADER_META = bytes.fromhex('00000000ce09f5f4000000000c729f9e8872b8bd00a06b02000000000079'
                            '510000000000000000000000000000000000000000000000000000000000')
assert len(HEADER_META) == 60


def load_inputs(weapon, taken_elsewhere=()):
    """Reads one weapon's game bank, the warning and its cue, finds the hooks and checks the new ids are free."""
    with open(os.path.join(GAME, weapon['bank'] + '.wwise_bank.main'), 'rb') as f:
        source = f.read()
    with open(os.path.join(GAME, weapon['bank'] + '.wwise_dep.main'), 'rb') as f:
        dep = f.read()
    bank0 = wb.Bank(source)
    resource = resource_hash('content/audio/' + weapon['bank'])
    assert bank0.resource_id == resource, '%s: the bank is not content/audio/%s' % (weapon['key'], weapon['bank'])
    hook, notes = discover(bank0, weapon['bank'])
    for n in notes:
        print('  note (%s):' % weapon['key'], n)
    names = ('wem', 'sound', 'play', 'stop', 'stop_fire', 'curve') + tuple('stop_%d' % i for i in range(len(hook['other_stoppers'])))
    ids = {k: wb.fnv1_32(weapon['id_prefix'] + k) for k in names}
    taken = bank0.ids() | set(taken_elsewhere)
    game_ids = os.path.join(GAME, 'game_ids.txt')
    if os.path.exists(game_ids):
        with open(game_ids) as f:
            for line in f:
                taken.update(int(x) for x in line.split()[1:])
    clash = [k for k, v in ids.items() if v in taken]
    assert not clash, '%s: id clash: %s' % (weapon['key'], clash)

    with wave.open(os.path.join(ROOT, 'assets', 'warning.wav')) as w:
        channels, rate, pcm = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
        length_s = w.getnframes() / rate
    cue_s = length_s                     # the moment in the sound that must land at full damage (sound.py writes it)
    cue_file = os.path.join(ROOT, 'assets', 'warning.json')
    if os.path.exists(cue_file):
        with open(cue_file) as f:
            cue_s = json.load(f)['cue_s']
    assert 0 < cue_s <= length_s, 'cue %.3f s is outside the %.3f s sound' % (cue_s, length_s)
    wem, wem_hash = wb.pcm_wem(pcm, channels, rate)
    stamp = dict(game_bank_md5=hashlib.md5(source).hexdigest(), **hook)
    return dict(weapon=weapon, source=source, dep=dep, resource=resource, hook=hook, ids=ids, wem=wem,
                wem_hash=wem_hash, delay_ms=round((weapon['end_at_s'] - cue_s) * 1000), stamp=stamp)


def build_bank(inp, volume_db=VOICE_VOLUME_DB):
    """The game's bank plus the warning: one sound, one Play and its Stop actions (additive only)."""
    bank, hook, ids, wp = wb.Bank(inp['source']), inp['hook'], inp['ids'], inp['weapon']
    bank.add_media(ids['wem'], inp['wem'])
    curve = [(0.0, -1.0, wb.CURVE_HOLD), (wp['silent_up_to'], -1.0, wb.CURVE_LINEAR), (wp['full_from'], 0.0, wb.CURVE_HOLD),
             (1.0, 0.0, wb.CURVE_LINEAR)]
    snd = wb.sound(ids['sound'], ids['wem'], inp['wem_hash'], len(inp['wem']), hook['mixer'],
                   [(0x05, volume_db), (0x4A, 0.0)], hook['charge_rtpc'], ids['curve'], curve)
    bank.insert_objects_after(hook['anchor'], [(wb.T_SOUND, snd)])  # next to the weapon's other charge sounds
    bank.add_child(hook['mixer'], ids['sound'])

    actions = [(wb.T_ACTION, wb.play_action(ids['play'], ids['sound'], hook['bank_id'], inp['delay_ms'])),
               (wb.T_ACTION, wb.stop_action(ids['stop'], ids['sound'], STOP_FADE_MS))]
    if hook['fire_event']:
        actions.append((wb.T_ACTION, wb.stop_action(ids['stop_fire'], ids['sound'], STOP_FADE_MS)))
    for i, _ in enumerate(hook['other_stoppers']):
        actions.append((wb.T_ACTION, wb.stop_action(ids['stop_%d' % i], ids['sound'], STOP_FADE_MS)))
    bank.insert_objects_before_events(actions)
    bank.append_event_action(hook['charge_event'], ids['play'])
    bank.append_event_action(hook['charge_end_event'], ids['stop'])
    if hook['fire_event']:
        bank.append_event_action(hook['fire_event'], ids['stop_fire'])
    for i, ev in enumerate(hook['other_stoppers']):
        bank.append_event_action(ev, ids['stop_%d' % i])
    return bank.to_resource()


def patch_archive(entries):
    """Stingray patch archive: 72-byte header, one row per resource type, 80-byte entry rows, 16-byte aligned data."""
    types = sorted({t for t, _, _ in entries}, key=[e[0] for e in entries].index)
    head = struct.pack('<III', 0xF0000011, len(types), len(entries)) + HEADER_META
    head += b''.join(struct.pack('<QQQII', 0, t, sum(e[0] == t for e in entries), 16, 64) for t in types)
    pos = len(head) + 80 * len(entries)
    rows, body = b'', b''
    for i, (t, rid, data) in enumerate(entries):
        pad = -pos % 16
        body += b'\0' * pad; pos += pad
        rows += struct.pack('<7Q6I', rid, t, pos, 0, 0, 0, 0, len(data), 0, 0, 16, 64, i)
        body += data; pos += len(data)
    out = head + rows + body
    return out + b'\0' * (-len(out) % 16)


def resource_hash(name):
    """Stingray resource id: MurmurHash64A (seed 0) of the resource name."""
    data, mask, m = name.encode('utf-8'), (1 << 64) - 1, 0xC6A4A7935BD1E995
    h = (len(data) * m) & mask
    n8 = len(data) // 8 * 8
    for (k,) in struct.iter_unpack('<Q', data[:n8]):
        k = (k * m) & mask; k ^= k >> 47; k = (k * m) & mask
        h = ((h ^ k) * m) & mask
    if data[n8:]:
        h = ((h ^ int.from_bytes(data[n8:], 'little')) * m) & mask
    h ^= h >> 47; h = (h * m) & mask; h ^= h >> 47
    return h


def auto_unsafe_archive(tester=False):
    """The option's patch: one plaintext Lua addon resource ('-- HD2-Addon: <module>' first line) in a Lua archive."""
    with open(os.path.join(HERE, 'auto_unsafe.lua'), encoding='utf-8') as f:
        src = f.read()
    for a, b in (('@@VERSION@@', VERSION + (' Test %d' % TEST if TEST else '')), ('@@TESTER@@', 'true' if TEST or tester else 'false'),
                 ('@@TESTBUILD@@', 'true' if TEST else 'false')):
        assert src.count(a) == 1, a
        src = src.replace(a, b)
    assert src.startswith('-- HD2-Addon: ' + AUTO_UNSAFE_MODULE + '\n')
    data = src.encode('utf-8')
    data = struct.pack('<II', len(data), 2) + data
    rows_at = 72 + 32
    pos = rows_at + 80
    row = struct.pack('<7Q6I', resource_hash(AUTO_UNSAFE_MODULE), LUA_TYPE, pos, 0, 0, 0, 0, len(data), 0, 0, 16, 16, 0)
    total = pos + len(data)
    head = struct.pack('<III', 0xF0000011, 1, 1) + b'\0' * 20 + struct.pack('<I', total) + b'\0' * 36
    return head + struct.pack('<QQQII', 0, LUA_TYPE, 1, 16, 16) + row + data


def write_zip(zip_path, manifest, variants, tester=False):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest, indent=2))
        z.write(os.path.join(ROOT, 'art', 'thumbnail_512.png'), 'thumbnail.png')
        for icon in sorted({w['icon'] for w in WEAPONS} | {'unsafe'} | {lv[3] for lv in VOLUME_LEVELS}):
            z.write(os.path.join(ROOT, 'art', 'options', icon + '.png'), 'options/%s.png' % icon)
        for folder, archive in variants:
            z.writestr(folder + '/' + ARCHIVE, archive)
            z.writestr(folder + '/' + ARCHIVE + '.gpu_resources', b'')
            z.writestr(folder + '/' + ARCHIVE + '.stream', b'')
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE, auto_unsafe_archive(tester))
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE + '.gpu_resources', b'')
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE + '.stream', b'')
    import verify                              # every zip is checked before the build can finish
    if verify.main(zip_path) != 0:
        os.remove(zip_path)
        raise SystemExit('verify.py found problems: %s was not kept' % os.path.basename(zip_path))
    print(zip_path)


def main():
    inputs, taken = [], set()
    for w in WEAPONS:
        inp = load_inputs(w, taken)
        taken |= set(inp['ids'].values())          # every new id is unique across all the mod's banks too
        inputs.append(inp)
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    variants, options = [], []
    for inp in inputs:
        w, sub_options = inp['weapon'], []
        for label, offset, blurb, icon in VOLUME_LEVELS:
            bank = build_bank(inp, VOICE_VOLUME_DB + offset)
            folder = w['folder'] + '/' + label.split(' (')[0]
            variants.append((folder, patch_archive([(T_BANK, inp['resource'], bank), (T_DEP, inp['resource'], inp['dep'])])))
            sub_options.append({'Name': label, 'Description': blurb, 'Image': 'options/%s.png' % icon, 'Include': [folder]})
        options.append({'Name': w['option'], 'Image': 'options/%s.png' % w['icon'], 'Description': w['blurb'],
                        'SubOptions': sub_options})
    options.append({'Name': 'Auto unsafe mode', 'Image': 'options/unsafe.png', 'Include': [AUTO_UNSAFE_DIR],
                    'Description': 'Every new Railgun you pick up starts in Unsafe mode instead of Safe. It is set once '
                                   'per Railgun: switch back to Safe and it stays Safe. Only your own Railgun. Needs '
                                   'Bingus Shared Loader v19 or newer; turn it off if you don\'t use the loader.'})
    base = os.path.join(ROOT, 'build', FILE_BASE + '-' + VERSION)
    if TEST:
        manifest = {'Version': 1, 'Guid': GUID_TEST, 'Name': '%s %s Test %d' % (NAME, VERSION, TEST),
                    'Description': 'TEST BUILD %d: installs next to the release; enable only one of them. ' % TEST + DESCRIPTION,
                    'IconPath': 'thumbnail.png', 'Options': options}
        write_zip(base + '-Test-%d.zip' % TEST, manifest, variants)
    else:
        # the release, and its Tester (the same build with the extra log lines, on the test GUID)
        write_zip(base + '.zip', {'Version': 1, 'Guid': GUID, 'Name': NAME, 'Description': DESCRIPTION,
                                  'IconPath': 'thumbnail.png', 'Options': options}, variants)
        write_zip(base + '-Tester.zip', {'Version': 1, 'Guid': GUID_TEST, 'Name': '%s %s (Tester)' % (NAME, VERSION),
                                         'Description': 'PERSONAL TESTER BUILD: the release plus extra log lines. Install '
                                                        'instead of the release, not next to it. ' + DESCRIPTION,
                                         'IconPath': 'thumbnail.png', 'Options': options}, variants, tester=True)
    for folder, archive in variants:                                          # the Loud levels, for checks
        if folder.endswith('/Loud'):
            with open(os.path.join(ROOT, 'build', folder.split('/')[0].lower() + '.' + ARCHIVE), 'wb') as f:
                f.write(archive)
    with open(os.path.join(GAME, 'built_from.json'), 'w') as f:                # update.py compares against this
        json.dump({'version': VERSION, 'weapons': {inp['weapon']['bank']: inp['stamp'] for inp in inputs}}, f, indent=2)
    for inp in inputs:
        print('%s: %d volume levels, play delay %d ms, stops on %d events' % (
            inp['weapon']['title'], len(VOLUME_LEVELS), inp['delay_ms'],
            1 + bool(inp['hook']['fire_event']) + len(inp['hook']['other_stoppers'])))


if __name__ == '__main__':
    main()
