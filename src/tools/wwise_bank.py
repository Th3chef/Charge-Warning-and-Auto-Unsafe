"""Minimal reader/writer for the Wwise sound banks Helldivers 2 ships as `wwise_bank` resources.

Only what this mod needs: split a bank into chunks, read/replace the object list (HIRC) and the embedded
audio (DIDX + DATA), and write new Sound / Action objects. Layouts are for the game's current Wwise version
(the one with a 'hash' chunk in every .wem and a media hash in every Sound)."""
import hashlib
import struct

T_SOUND, T_ACTION, T_EVENT, T_ACTOR_MIXER = 2, 3, 4, 7
ACTION_PLAY, ACTION_STOP = 0x0403, 0x0103
PROP_DELAY_MS, PROP_FADE_MS = 0x3A, 0x3B
CODEC_PCM = 0x00010001
CURVE_HOLD, CURVE_LINEAR = 9, 4
SCALING_DB = 2                      # volume curves: y = -1 is silence, 0 is full volume
PARAM_VOLUME = 0


def fnv1_32(name):
    """Wwise object ids are FNV-1 (32-bit) hashes of lower-case names."""
    h = 0x811C9DC5
    for c in name.lower().encode():
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= c
    return h


class Bank:
    def __init__(self, resource):
        # resource = 16-byte Stingray header (u32 tag, u32 size of the rest, u64 resource id) + Wwise chunks
        self.tag, _, self.resource_id = struct.unpack_from('<IIQ', resource, 0)
        self.chunks = []
        pos = 16
        while pos < len(resource):
            name, size = resource[pos:pos + 4], struct.unpack_from('<I', resource, pos + 4)[0]
            self.chunks.append([name, resource[pos + 8:pos + 8 + size]])
            pos += 8 + size
        self.objects = self._read_objects(self.chunk(b'HIRC'))
        self.media = self._read_media(self.chunk(b'DIDX'), self.chunk(b'DATA'))

    def chunk(self, name):
        return next(data for n, data in self.chunks if n == name)

    def _set_chunk(self, name, data):
        next(c for c in self.chunks if c[0] == name)[1] = data

    @staticmethod
    def _read_objects(hirc):
        count, pos, objects = struct.unpack_from('<I', hirc, 0)[0], 4, []
        for _ in range(count):
            kind, size = hirc[pos], struct.unpack_from('<I', hirc, pos + 1)[0]
            objects.append([kind, bytearray(hirc[pos + 5:pos + 5 + size])])
            pos += 5 + size
        assert pos == len(hirc)
        return objects

    @staticmethod
    def _read_media(didx, data):
        entries = [struct.unpack_from('<III', didx, i) for i in range(0, len(didx), 12)]
        return [(wem_id, data[offset:offset + size]) for wem_id, offset, size in entries]

    def find(self, object_id):
        for kind, body in self.objects:
            if struct.unpack_from('<I', body, 0)[0] == object_id:
                return kind, body
        raise KeyError(object_id)

    def ids(self):
        return {struct.unpack_from('<I', body, 0)[0] for _, body in self.objects} | {w for w, _ in self.media}

    # ---- edits
    def add_media(self, wem_id, wem):
        self.media.append((wem_id, wem))

    def insert_objects_after(self, anchor_id, new):
        i = next(i for i, (_, b) in enumerate(self.objects) if struct.unpack_from('<I', b, 0)[0] == anchor_id)
        self.objects[i + 1:i + 1] = [[k, bytearray(b)] for k, b in new]

    def insert_objects_before_events(self, new):
        i = next(i for i, (k, _) in enumerate(self.objects) if k == T_EVENT)
        self.objects[i:i] = [[k, bytearray(b)] for k, b in new]

    def append_event_action(self, event_id, action_id):
        _, body = self.find(event_id)
        actions = list(struct.unpack_from('<%dI' % body[4], body, 5)) + [action_id]
        body[:] = struct.pack('<IB', event_id, len(actions)) + struct.pack('<%dI' % len(actions), *actions)

    def add_child(self, parent_id, child_id):
        """Containers end with their child list: u32 count, then the child ids in ascending order."""
        _, body = self.find(parent_id)
        for count in range(1, 1024):
            start = len(body) - 4 - 4 * count
            if struct.unpack_from('<I', body, start)[0] == count:
                break
        children = sorted(struct.unpack_from('<%dI' % count, body, start + 4) + (child_id,))
        body[start:] = struct.pack('<I', len(children)) + struct.pack('<%dI' % len(children), *children)

    # ---- output
    def to_resource(self):
        didx, data = b'', bytearray()
        for wem_id, wem in self.media:
            data += b'\0' * (-len(data) % 16)
            didx += struct.pack('<III', wem_id, len(data), len(wem))
            data += wem
        self._set_chunk(b'DIDX', didx)
        self._set_chunk(b'DATA', bytes(data))
        self._set_chunk(b'HIRC', struct.pack('<I', len(self.objects)) + b''.join(
            bytes([k]) + struct.pack('<I', len(b)) + bytes(b) for k, b in self.objects))
        body = b''.join(n + struct.pack('<I', len(d)) + d for n, d in self.chunks)
        return struct.pack('<IIQ', self.tag, len(body), self.resource_id) + body


def pcm_wem(samples_le16, channels, rate):
    """16-bit PCM .wem: WAVE_FORMAT_EXTENSIBLE with the Wwise channel layout, plus a 'hash' chunk (md5 of the audio)."""
    layout = {1: 0x4101, 2: 0x3102}[channels]          # channel count | standard config | speaker mask (C / L+R)
    fmt = struct.pack('<HHIIHHHHI', 0xFFFE, channels, rate, rate * 2 * channels, 2 * channels, 16, 6, 0, layout)
    digest = hashlib.md5(samples_le16).digest()
    def chunk(name, data):
        return name + struct.pack('<I', len(data)) + data + b'\0' * (len(data) & 1)
    riff = b'WAVE' + chunk(b'fmt ', fmt) + chunk(b'hash', digest) + chunk(b'data', samples_le16)
    return b'RIFF' + struct.pack('<I', len(riff)) + riff, struct.unpack('<I', digest[:4])[0]


def sound(sound_id, wem_id, wem_hash, wem_size, parent_id, props, rtpc_id, curve_id, points):
    """An embedded PCM Sound whose volume follows one game parameter (RTPC) through `points` [(x, y, shape)]."""
    out = struct.pack('<IIBIIIB', sound_id, CODEC_PCM, 0, wem_id, wem_hash, wem_size, 0)
    out += bytes(4) + struct.pack('<I', 0)                               # no effects / metadata overrides, no bus override
    out += struct.pack('<IB', parent_id, 0)                              # parent, no priority override
    out += struct.pack('<B', len(props)) + bytes(k for k, _ in props) + b''.join(struct.pack('<f', v) for _, v in props)
    out += bytes([0, 0, 0]) + struct.pack('<I', 0)                       # no ranged props, positioning, aux sends, reflections bus
    out += bytes([0, 1, 1, 0, 3, 0])                                     # advanced settings: the railgun charge sounds' values
    out += bytes([0, 0])                                                 # no states
    out += struct.pack('<H', 1)                                          # one RTPC curve:
    out += struct.pack('<IBBBIBH', rtpc_id, 0, 2, PARAM_VOLUME, curve_id, SCALING_DB, len(points))
    out += b''.join(struct.pack('<ffI', x, y, shape) for x, y, shape in points)
    return out


def play_action(action_id, target_id, bank_id, delay_ms=0):
    props = struct.pack('<BBI', 1, PROP_DELAY_MS, delay_ms) if delay_ms else b'\0'
    return struct.pack('<IHIB', action_id, ACTION_PLAY, target_id, 0) + props + struct.pack('<BBII', 0, 4, bank_id, 0)


def stop_action(action_id, target_id, fade_ms):
    return struct.pack('<IHIB', action_id, ACTION_STOP, target_id, 0) + struct.pack('<BBI', 1, PROP_FADE_MS, fade_ms) \
        + bytes([0, 4, 6, 0])                                            # no ranged props, linear fade, stop flags, no exceptions
