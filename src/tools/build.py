"""Builds Railgun Warning & Auto Unsafe (formerly Railgun Overcharge Warning) from the game's own railgun sound bank.

Inputs (../game/, extracted from the game with Filediver, see README.md):
    wep_railgun.wwise_bank.main, wep_railgun.wwise_dep.main   the game's content/audio/wep_railgun
    game_ids.txt (optional)                                    every object/audio id in the game's banks, for a clash check
    ../assets/warning.wav                                      the warning sound (sound.py)
    ../art/thumbnail_512.png, ../art/options/*.png             Arsenal icons (art.py)
    auto_unsafe.lua                                            the "Auto unsafe mode" option (a Bingus Shared Loader addon)
Output: ../build/<zip>, ready for Arsenal / the HD2 mod manager.
    python build.py            release
    python build.py test N     test build N: "<version> Test N", its own GUID (installs next to the release), tester logging"""
import json, os, struct, sys, wave, zipfile
import hashlib
import wwise_bank as wb
from discover import discover

NAME = 'Railgun Warning & Auto Unsafe'
FILE_BASE = 'Railgun-Warning-and-Auto-Unsafe'      # zip names (no '&': Nexus file names allow only letters, digits, spaces and _ ' ( ) . -)
VERSION = '2.0.1'
GUID = 'c8736b4d-7681-43b3-ac5e-03314f2d7034'
GUID_TEST = '6cf144dc-0353-4f83-9da1-b57f2875bce7'   # test builds
TEST = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == 'test' else 0
DESCRIPTION = ('A warning for the RS-422 Railgun in unsafe mode: a growling electric surge with fast warning beeps that start '
               'exactly as the charge reaches 90% (full damage), so you know when to fire before it overloads. Silent in safe '
               'mode and on quick shots, and it stops the moment you fire or let go. Option: Auto unsafe mode - every new '
               'Railgun you pick up starts in Unsafe (needs Bingus Shared Loader).')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GAME = os.environ.get('RCW_GAME_DIR', os.path.join(ROOT, 'game'))   # where the extracted game bank lives

# ---- what the mod hooks into (charge event, charge-end event, charge value, mixer...) is found in the game's
#      bank by discover.py each build, so a patched bank only needs re-extracting and rebuilding (update.py).
VOICE_VOLUME_DB = 10.0      # prop 0x05 = voice volume in dB (the railgun's charge whine uses +4); the "Loud" level

# ---- Arsenal "Warning volume" option: one pick-one sub-option per level (dB added to VOICE_VOLUME_DB); first = default.
#      Arsenal drops an option whose Include is an empty list, so the option itself carries no Include key at all.
VOLUME_LEVELS = [
    ('Loud', 0, 'Full volume (the level of 1.0.1): clearly audible over the charge-up.', 'vol_3'),
    ('Medium (-8 dB)', -8, 'Noticeably quieter than Loud.', 'vol_2'),
    ('Quiet (-16 dB)', -16, 'A subtle cue, well below Loud.', 'vol_1'),
]

# ---- behaviour
SILENT_UP_TO, FULL_FROM = 0.75, 0.76      # charge value: silent at or below 0.75 (safe mode can't get there)
END_AT_S = 2.5                            # an unsafe charge reaches 90% (full damage) 2.5 s in: the cue lands here
STOP_FADE_MS = 100

# ---- Arsenal "Auto unsafe mode" option: a Bingus Shared Loader Lua addon in its own folder (on by default)
AUTO_UNSAFE_DIR = 'Auto Unsafe'
AUTO_UNSAFE_MODULE = 'mods/chef/railgun_auto_unsafe'
LUA_TYPE = 0xA14E8DFA2CD117E2

ARCHIVE = '9ba626afa44a3aa3.patch_0'
T_BANK, T_DEP = 0x535A7BD3E650D799, 0xAF32095C82F2B070
RESOURCE = 0xFC90B1C2172E00CB             # content/audio/wep_railgun
# engine metadata bytes 12..72 of the patch header. Audio patches need this exact block: every working audio mod
# checked (9 of them, several authors) carries it, and a sound bank patch with the material-mod header loads but
# stays silent.
HEADER_META = bytes.fromhex('00000000ce09f5f4000000000c729f9e8872b8bd00a06b02000000000079'
                            '510000000000000000000000000000000000000000000000000000000000')
assert len(HEADER_META) == 60


def new_id(what):
    return wb.fnv1_32('chef_railgun_charge_warning_' + what)


def load_inputs():
    """Reads the game bank, the warning and its cue once, finds the hooks and checks the new ids are free."""
    with open(os.path.join(GAME, 'wep_railgun.wwise_bank.main'), 'rb') as f:
        source = f.read()
    with open(os.path.join(GAME, 'wep_railgun.wwise_dep.main'), 'rb') as f:
        dep = f.read()
    hook, notes = discover(wb.Bank(source))
    for n in notes:
        print('  note:', n)
    ids = {k: new_id(k) for k in ('wem', 'sound', 'play', 'stop', 'stop_fire', 'curve')}
    taken = wb.Bank(source).ids()
    game_ids = os.path.join(GAME, 'game_ids.txt')
    if os.path.exists(game_ids):
        with open(game_ids) as f:
            for line in f:
                taken.update(int(x) for x in line.split()[1:])
    clash = [k for k, v in ids.items() if v in taken]
    assert not clash, 'id clash: %s' % clash

    with wave.open(os.path.join(ROOT, 'assets', 'warning.wav')) as w:
        channels, rate, pcm = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
        length_s = w.getnframes() / rate
    cue_s = length_s                     # the moment in the sound that must land at 90% charge (sound.py writes it)
    cue_file = os.path.join(ROOT, 'assets', 'warning.json')
    if os.path.exists(cue_file):
        with open(cue_file) as f:
            cue_s = json.load(f)['cue_s']
    assert 0 < cue_s <= length_s, 'cue %.3f s is outside the %.3f s sound' % (cue_s, length_s)
    wem, wem_hash = wb.pcm_wem(pcm, channels, rate)
    stamp = dict(game_bank_md5=hashlib.md5(source).hexdigest(), version=VERSION, **hook)
    return dict(source=source, dep=dep, hook=hook, ids=ids, wem=wem, wem_hash=wem_hash,
                delay_ms=round((END_AT_S - cue_s) * 1000), stamp=stamp)


def build_bank(inp, volume_db=VOICE_VOLUME_DB):
    """The game's bank plus the warning: one sound, one Play and two Stop actions (additive only)."""
    bank, hook, ids = wb.Bank(inp['source']), inp['hook'], inp['ids']
    bank.add_media(ids['wem'], inp['wem'])
    curve = [(0.0, -1.0, wb.CURVE_HOLD), (SILENT_UP_TO, -1.0, wb.CURVE_LINEAR), (FULL_FROM, 0.0, wb.CURVE_HOLD),
             (1.0, 0.0, wb.CURVE_LINEAR)]
    snd = wb.sound(ids['sound'], ids['wem'], inp['wem_hash'], len(inp['wem']), hook['mixer'],
                   [(0x05, volume_db), (0x4A, 0.0)], hook['charge_rtpc'], ids['curve'], curve)
    bank.insert_objects_after(hook['anchor'], [(wb.T_SOUND, snd)])  # next to the railgun's other charge sounds
    bank.add_child(hook['mixer'], ids['sound'])

    actions = [(wb.T_ACTION, wb.play_action(ids['play'], ids['sound'], hook['bank_id'], inp['delay_ms'])),
               (wb.T_ACTION, wb.stop_action(ids['stop'], ids['sound'], STOP_FADE_MS))]
    if hook['fire_event']:
        actions.append((wb.T_ACTION, wb.stop_action(ids['stop_fire'], ids['sound'], STOP_FADE_MS)))
    bank.insert_objects_before_events(actions)
    bank.append_event_action(hook['charge_event'], ids['play'])
    bank.append_event_action(hook['charge_end_event'], ids['stop'])
    if hook['fire_event']:
        bank.append_event_action(hook['fire_event'], ids['stop_fire'])
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
        for icon in ['volume', 'unsafe'] + [lv[3] for lv in VOLUME_LEVELS]:
            z.write(os.path.join(ROOT, 'art', 'options', icon + '.png'), 'options/%s.png' % icon)
        for folder, archive in variants:
            z.writestr(folder + '/' + ARCHIVE, archive)
            z.writestr(folder + '/' + ARCHIVE + '.gpu_resources', b'')
            z.writestr(folder + '/' + ARCHIVE + '.stream', b'')
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE, auto_unsafe_archive(tester))
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE + '.gpu_resources', b'')
        z.writestr(AUTO_UNSAFE_DIR + '/' + ARCHIVE + '.stream', b'')
    print(zip_path)


def main():
    inp = load_inputs()
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    variants, sub_options = [], []
    for label, offset, blurb, icon in VOLUME_LEVELS:
        bank = build_bank(inp, VOICE_VOLUME_DB + offset)
        folder = 'Volume/' + label.split(' (')[0]
        variants.append((folder, patch_archive([(T_BANK, RESOURCE, bank), (T_DEP, RESOURCE, inp['dep'])])))
        sub_options.append({'Name': label, 'Description': blurb, 'Image': 'options/%s.png' % icon, 'Include': [folder]})
    options = [{'Name': 'Warning volume', 'Image': 'options/volume.png',
                'Description': 'How loud the warning plays. Pick one level: Loud, Medium or Quiet.',
                'SubOptions': sub_options},
               {'Name': 'Auto unsafe mode', 'Image': 'options/unsafe.png', 'Include': [AUTO_UNSAFE_DIR],
                'Description': 'Every new Railgun you pick up starts in Unsafe mode instead of Safe. It is set once '
                               'per Railgun: switch back to Safe and it stays Safe. Only your own Railgun. Needs '
                               'Bingus Shared Loader; turn it off if you don\'t use the loader.'}]
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
    with open(os.path.join(ROOT, 'build', ARCHIVE), 'wb') as f:                 # the Loud level, for checks
        f.write(variants[0][1])
    with open(os.path.join(GAME, 'built_from.json'), 'w') as f:                # update.py compares against this
        json.dump(inp['stamp'], f, indent=2)
    print(len(variants), 'volume levels,', len(variants[0][1]), 'bytes each, play delay', inp['delay_ms'], 'ms')


if __name__ == '__main__':
    main()
