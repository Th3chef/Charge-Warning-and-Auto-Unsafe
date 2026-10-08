"""Finds what the mod hooks into in whatever version of a game weapon bank it is given, by what things do rather
than by fixed ids, so a game patch that reshuffles a bank does not break the build. Works for every charge weapon
the mod covers (the RS-422 Railgun's wep_railgun, the PLAS-45 Epoch's wep_plasma_blaster).

    charge event      the event that starts the charge-up: it plays sounds and also has Seek actions on them
    charge RTPC       the game parameter (0..1) that most of the charge sounds (and their containers) follow
    charge-end event  the event that stops most of the charge event's sounds (the release / charge-stop event)
    fire event        the weapon's shot event, found by its name (Wwise ids are hashes of the names: wep_<bank>_fire)
    other stoppers    any other event that also stops the charge sounds (the Epoch has a second shot event)
    mixer             the actor-mixer the charge sounds sit under
    bank id           the id this bank's own Play actions carry
Known ids from the October 2026 game are used to cross-check; if a role moved, the build says so."""
import struct
from collections import Counter
import wwise_bank as wb

ACTION_SEEK = 0x1E03
T_LAYER_CNTR, T_RANSEQ_CNTR, T_SWITCH_CNTR = 9, 5, 6
WWISE_VERSION = 0x9211BC36          # first field of BKHD in the banks this code was written for

# cross-check only: what each role was in the October 2026 game (the build never relies on these)
KNOWN = {
    'wep_railgun': dict(charge_event=776670436, charge_end_event=1887886872, fire_event=2040339267, mixer=25230646,
                        charge_rtpc=0xBFDCF9F2, bank_id=0x10BC18A8, anchor=934480751, other_stoppers=[]),
    'wep_plasma_blaster': dict(charge_event=1805360771, charge_end_event=2230772993, fire_event=58321,
                               mixer=736237980, charge_rtpc=0xBFDCF9F2, bank_id=0xCBBE4836, anchor=385178441,
                               other_stoppers=[1613947930]),
}


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


def _rtpcs(body, start=30):
    """RTPC ids whose curve runs over 0..1 in an object (found by shape: id, type, accum, param, curve, scaling, points)."""
    found = []
    for o in range(start, len(body) - 26):
        rtype, accum, param, scaling, n = body[o + 4], body[o + 5], body[o + 6], body[o + 11], struct.unpack_from('<H', body, o + 12)[0]
        if rtype > 2 or accum > 4 or param > 0x40 or scaling > 4 or not 2 <= n <= 16 or o + 14 + 12 * n > len(body):
            continue
        pts = [struct.unpack_from('<ffI', body, o + 14 + 12 * k) for k in range(n)]
        xs = [p[0] for p in pts]
        if all(p[2] <= 9 for p in pts) and xs == sorted(xs) and xs[0] == 0.0 and xs[-1] == 1.0:
            found.append(u32(body, o))
    return found


def _parent(kind, body):
    """Sounds keep their parent at +30 (after the source block), containers at +12 (when they have no effects)."""
    if kind == wb.T_SOUND:
        return u32(body, 30)
    if kind in (T_RANSEQ_CNTR, T_SWITCH_CNTR, T_LAYER_CNTR, wb.T_ACTOR_MIXER) and body[5] == 0:
        return u32(body, 12)
    return None


def _children(bank, body):
    """Container child list: u32 count + that many ascending ids of objects in the bank (searched from the end)."""
    ids = bank.ids()
    for o in range(len(body) - 8, 3, -1):
        n = u32(body, o)
        if 1 <= n <= 256 and o + 4 + 4 * n <= len(body):
            kids = list(struct.unpack_from('<%dI' % n, body, o + 4))
            if kids == sorted(kids) and all(k in ids for k in kids):
                return kids
    return []


def discover(bank, bank_name):
    info, notes = {}, []
    bkhd = bank.chunk(b'BKHD')
    if u32(bkhd, 0) != WWISE_VERSION:
        notes.append('WARNING: the bank was written by a different Wwise version (0x%08x); check wwise_bank.py layouts '
                     'before shipping' % u32(bkhd, 0))
    acts, events = _actions(bank), _events(bank)
    kinds = {u32(b, 0): k for k, b in bank.objects}

    # charge event: plays sounds and seeks in them
    cands = [ev for ev, ids in events.items()
             if {wb.ACTION_PLAY, ACTION_SEEK} <= {acts[a][0] for a in ids if a in acts}]
    assert len(cands) == 1, 'charge event not found uniquely: %s' % cands
    info['charge_event'] = ev_charge = cands[0]
    played = [acts[a][1] for a in events[ev_charge] if a in acts and acts[a][0] == wb.ACTION_PLAY]

    # charge RTPC: the 0..1 parameter most charge objects follow (the objects the charge event plays, and what they hold)
    votes, followers = Counter(), []
    for t in played:
        if t not in kinds:
            continue
        k, body = bank.find(t)
        found = set(_rtpcs(body, 30 if k == wb.T_SOUND else 12))
        for kid in (_children(bank, body) if k != wb.T_SOUND else []):
            found |= set(_rtpcs(bank.find(kid)[1]))
        votes.update(found)
        followers.append((t, found))
    assert votes, 'no 0..1 game parameter on the charge sounds'
    info['charge_rtpc'] = rtpc = votes.most_common(1)[0][0]

    # charge-end event: stops the most charge targets (it may also play its own power-down sounds)
    fire_id = wb.fnv1_32(bank_name + '_fire')
    def stopped(ev):
        return {acts[a][1] for a in events[ev] if a in acts and acts[a][0] == wb.ACTION_STOP} & set(played)
    ranked = sorted((len(stopped(ev)), ev) for ev in events if ev not in (ev_charge, fire_id))
    best_hits, best = ranked[-1]
    assert best_hits * 2 >= len(played), 'charge-end event not found (best stops %d of %d)' % (best_hits, len(played))
    info['charge_end_event'] = best

    # fire event: by its name (wep_<bank>_fire); optional, the charge-end event still stops the warning on release
    info['fire_event'] = fire_id if fire_id in events else None
    if info['fire_event'] is None:
        notes.append('fire event %s_fire not found: the warning is still stopped on release by the charge-end event'
                     % bank_name)
    # other events that also cut the charge sounds (2 or more of them): the warning stops there too
    info['other_stoppers'] = sorted(ev for ev in events if ev not in (ev_charge, best, info['fire_event'])
                                    and len(stopped(ev)) >= 2)

    # mixer: the actor-mixer the charge objects share
    parents = Counter()
    for t in played:
        if t in kinds:
            p = _parent(*bank.find(t))
            if p is not None and kinds.get(p) == wb.T_ACTOR_MIXER:
                parents[p] += 1
    assert parents, 'no actor-mixer above the charge sounds'
    info['mixer'] = parents.most_common(1)[0][0]

    # anchor: where the new sound is listed (next to a charge sound that follows the charge value, else the first one)
    sounds = [t for t in played if kinds.get(t) == wb.T_SOUND]
    assert sounds, 'the charge event plays no sound directly'
    known = KNOWN.get(bank_name, {})
    rtpc_sounds = [t for t, f in followers if kinds.get(t) == wb.T_SOUND and rtpc in f]
    info['anchor'] = known.get('anchor') if known.get('anchor') in sounds else (rtpc_sounds or sounds)[0]

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

    for k, v in known.items():
        if k != 'anchor' and info.get(k) != v:
            notes.append('%s moved: %s (was %s)' % (k, info.get(k), v))
    return info, notes
