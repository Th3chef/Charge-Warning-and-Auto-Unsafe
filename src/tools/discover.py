"""Finds what the mod hooks into in whatever version of the game's railgun bank it is given, by what things do
rather than by fixed ids, so a game patch that reshuffles the bank does not break the build.

    charge event      the event that starts the charge-up: it plays sounds and also has Seek actions on them
    charge RTPC       the game parameter (0..1) that most of those charge sounds follow
    charge-end event  the event that only stops (most of) the charge event's sounds
    fire event        the shot event (optional: charge-end already stops the warning when you fire)
    mixer             the actor-mixer the charge sounds sit under
    bank id           the id this bank's own Play actions carry
Known ids from the September 2026 game are used to cross-check; if the roles moved, the build says so."""
import struct
from collections import Counter
import wwise_bank as wb

ACTION_SEEK = 0x1E03
KNOWN = dict(charge_event=776670436, charge_end_event=1887886872, fire_event=2040339267, mixer=25230646,
             charge_rtpc=0xBFDCF9F2, bank_id=0x10BC18A8, anchor=934480751)
WWISE_VERSION = 0x9211BC36          # first field of BKHD in the banks this code was written for


def u32(b, o):
    return struct.unpack_from('<I', b, o)[0]


def _actions(bank):
    out = {}
    for kind, b in bank.objects:
        if kind == wb.T_ACTION:
            out[u32(b, 0)] = (struct.unpack_from('<H', b, 4)[0], u32(b, 6), b)
    return out


def _events(bank):
    return {u32(b, 0): list(struct.unpack_from('<%dI' % b[4], b, 5)) for kind, b in bank.objects if kind == wb.T_EVENT}


def _sound_rtpcs(body):
    """RTPC ids whose curve runs over 0..1 in a Sound (found by shape: id, type, accum, param, curve, scaling, points)."""
    found = []
    for o in range(30, len(body) - 26):
        rtype, accum, param, scaling, n = body[o + 4], body[o + 5], body[o + 6], body[o + 11], struct.unpack_from('<H', body, o + 12)[0]
        if rtype > 2 or accum > 4 or param > 0x40 or scaling > 4 or not 2 <= n <= 16 or o + 14 + 12 * n > len(body):
            continue
        pts = [struct.unpack_from('<ffI', body, o + 14 + 12 * k) for k in range(n)]
        xs = [p[0] for p in pts]
        if all(p[2] <= 9 for p in pts) and xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 1.0:
            found.append(u32(body, o))
    return found


def discover(bank):
    info, notes = {}, []
    bkhd = bank.chunk(b'BKHD')
    if u32(bkhd, 0) != WWISE_VERSION:
        notes.append('WARNING: the bank was written by a different Wwise version (0x%08x); check wwise_bank.py layouts '
                     'before shipping' % u32(bkhd, 0))
    acts, events = _actions(bank), _events(bank)
    kinds = {u32(b, 0): k for k, b in bank.objects}

    # charge event: plays sounds and seeks in them
    cands = []
    for ev, ids in events.items():
        types = [acts[a][0] for a in ids if a in acts]
        if ACTION_SEEK in types and wb.ACTION_PLAY in types:
            cands.append(ev)
    assert len(cands) == 1, 'charge event not found uniquely: %s' % cands
    info['charge_event'] = ev_charge = cands[0]
    played = [acts[a][1] for a in events[ev_charge] if a in acts and acts[a][0] == wb.ACTION_PLAY]
    charge_sounds = [s for s in played if kinds.get(s) == wb.T_SOUND]

    # charge RTPC: the 0..1 parameter most charge sounds follow
    votes = Counter(r for s in charge_sounds for r in set(_sound_rtpcs(bank.find(s)[1])))
    assert votes, 'no 0..1 game parameter on the charge sounds'
    info['charge_rtpc'] = votes.most_common(1)[0][0]
    followers = [s for s in charge_sounds if info['charge_rtpc'] in _sound_rtpcs(bank.find(s)[1])]

    # charge-end event: only Stop actions, on the charge event's targets
    best, best_hits = None, 0
    for ev, ids in events.items():
        rows = [acts[a] for a in ids if a in acts]
        if rows and all(t == wb.ACTION_STOP for t, _, _ in rows):
            hits = sum(tg in played for _, tg, _ in rows)
            if hits > best_hits:
                best, best_hits = ev, hits
    assert best and best_hits * 2 >= len(played), 'charge-end event not found'
    info['charge_end_event'] = best

    # mixer: the parent the charge sounds share
    parents = Counter(u32(bank.find(s)[1], 30) for s in followers)
    info['mixer'] = parents.most_common(1)[0][0]
    info['anchor'] = KNOWN['anchor'] if KNOWN['anchor'] in followers else followers[0]   # where the new sound is listed

    # bank id: carried by this bank's own Play actions
    ids = Counter()
    for t, _, b in acts.values():
        if t == wb.ACTION_PLAY:
            k = b[11]
            pos = 12 + 5 * k
            r = b[pos]
            pos += 1 + 9 * r + 1
            if pos + 4 <= len(b):
                ids[u32(b, pos)] += 1
    info['bank_id'] = ids.most_common(1)[0][0]

    # fire event (optional): known id if it is still there
    info['fire_event'] = KNOWN['fire_event'] if KNOWN['fire_event'] in events else None
    if info['fire_event'] is None:
        notes.append('fire event not found: the warning is still stopped on release/fire by the charge-end event')

    for k, v in KNOWN.items():
        if k != 'anchor' and info.get(k) != v:
            notes.append('%s moved: %s (was %s)' % (k, info.get(k), v))
    return info, notes
