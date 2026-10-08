"""Offline check of a built mod zip against the game banks in ../game (no game needed):
    python verify.py <mod zip>
For every weapon and volume level it re-reads the patched bank and checks that
  - the game's bank is all still there: every original object and media file is present and unchanged, except the
    events the warning hooks into (only actions appended) and the mixer's child list (only the warning added);
  - the warning sound sits under the charge mixer, follows the charge value with the weapon's gate, at the level's volume;
  - the charge event plays it with the delay that puts its first beep on the weapon's full-damage moment;
  - it is stopped on release (charge-end), on the shot and on every other event that cuts the charge sounds.
Exit 0 = all good, 1 = something is wrong (it says what)."""
import io, json, os, struct, sys, wave, zipfile
import wwise_bank as wb
import build as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def events(bank):
    return {u32(b, 0): list(struct.unpack_from('<%dI' % b[4], b, 5)) for k, b in bank.objects if k == wb.T_EVENT}


def main(zpath):
    z = zipfile.ZipFile(zpath)
    manifest = json.loads(z.read('manifest.json'))
    problems = []
    with wave.open(os.path.join(ROOT, 'assets', 'warning.wav')) as w:
        cue_s = json.load(open(os.path.join(ROOT, 'assets', 'warning.json')))['cue_s']
    taken = set()
    for wp in B.WEAPONS:
        inp = B.load_inputs(wp, taken)
        taken |= set(inp['ids'].values())
        game, hook, ids = wb.Bank(inp['source']), inp['hook'], inp['ids']
        gobj = {u32(b, 0): (k, bytes(b)) for k, b in game.objects}
        gev = events(game)
        opt = next((o for o in manifest['Options'] if o['Name'] == wp['option']), None)
        if not opt:
            problems.append('%s: no "%s" option in the manifest' % (wp['key'], wp['option'])); continue
        for (label, offset, _, _), sub in zip(B.VOLUME_LEVELS, opt['SubOptions']):
            where = '%s %s' % (wp['title'], label.split(' (')[0])
            folder = sub['Include'][0]
            arc = z.read(folder + '/' + B.ARCHIVE)
            if arc[12:72] != B.HEADER_META:
                problems.append(where + ': not the audio patch header')
            n = u32(arc, 8)
            rows = [struct.unpack_from('<7Q6I', arc, 72 + 32 * u32(arc, 4) + 80 * i) for i in range(n)]
            bank_row = next(r for r in rows if r[1] == B.T_BANK)
            if bank_row[0] != inp['resource']:
                problems.append(where + ': bank resource id is not content/audio/' + wp['bank'])
            bank = wb.Bank(arc[bank_row[2]:bank_row[2] + bank_row[7]])
            obj = {u32(b, 0): (k, bytes(b)) for k, b in bank.objects}
            # 1. additive only
            changed = {hook['charge_event'], hook['charge_end_event'], hook['mixer']} | set(hook['other_stoppers'])
            if hook['fire_event']:
                changed.add(hook['fire_event'])
            for oid, (k, b) in gobj.items():
                if oid not in obj:
                    problems.append('%s: game object %d is missing' % (where, oid))
                elif oid not in changed and obj[oid] != (k, b):
                    problems.append('%s: game object %d was changed' % (where, oid))
            new = set(obj) - set(gobj)
            expect = {ids[k] for k in ids if k not in ('wem', 'curve')}
            if not hook['fire_event']:
                expect.discard(ids['stop_fire'])
            if new != expect:
                problems.append('%s: unexpected new objects %s' % (where, sorted(new ^ expect)))
            gmedia, media = dict(game.media), dict(bank.media)
            if any(media.get(m) != d for m, d in gmedia.items()) or set(media) - set(gmedia) != {ids['wem']}:
                problems.append(where + ': game media changed, or the warning media is missing')
            # 2. events: only our action appended
            ev = events(bank)
            for e, mine in [(hook['charge_event'], ids['play']), (hook['charge_end_event'], ids['stop']),
                            (hook['fire_event'], ids['stop_fire'])] + \
                           [(e, ids['stop_%d' % i]) for i, e in enumerate(hook['other_stoppers'])]:
                if e is None:
                    continue
                if ev.get(e) != gev[e] + [mine]:
                    problems.append('%s: event %d is not the game event plus the warning action' % (where, e))
            # 3. the sound
            k, snd = obj[ids['sound']]
            if u32(snd, 30) != hook['mixer']:
                problems.append(where + ': warning not under the charge mixer')
            nprops = snd[35]
            props = dict(zip(snd[36:36 + nprops], struct.unpack_from('<%df' % nprops, snd, 36 + nprops)))
            if abs(props.get(0x05, 99) - (B.VOICE_VOLUME_DB + offset)) > 1e-4:
                problems.append('%s: voice volume %.1f dB, expected %.1f' % (where, props.get(0x05, 99), B.VOICE_VOLUME_DB + offset))
            if struct.pack('<I', hook['charge_rtpc']) not in snd:
                problems.append(where + ': warning does not follow the charge value')
            pts = [struct.unpack_from('<ffI', snd, len(snd) - 12 * (4 - i)) for i in range(4)]
            if [round(p[0], 3) for p in pts] != [0.0, wp['silent_up_to'], wp['full_from'], 1.0]:
                problems.append('%s: gate points %s' % (where, [p[0] for p in pts]))
            # 4. the delay puts the first beep on the full-damage moment
            k, play = obj[ids['play']]
            delay = u32(play, 13) if play[11] == 1 and play[12] == wb.PROP_DELAY_MS else 0
            beep = (delay / 1000.0) + cue_s
            if abs(beep - wp['end_at_s']) > 0.0015:
                problems.append('%s: first beep at %.3f s, expected %.3f s' % (where, beep, wp['end_at_s']))
        print('%-15s beeps start %.2f s into the charge (play delay %d ms), gate %.2f-%.2f, stops on %d events' % (
            wp['title'], delay / 1000.0 + cue_s, delay, wp['silent_up_to'], wp['full_from'],
            1 + bool(hook['fire_event']) + len(hook['other_stoppers'])))
    for p in problems:
        print('PROBLEM:', p)
    print('all checks passed' if not problems else '%d problem(s)' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
