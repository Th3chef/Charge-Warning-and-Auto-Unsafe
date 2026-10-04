"""Synthesises the warning: "Arcing Surge" - a low, growling electric hum that swells and climbs, with crackling arcs
building up over it, fast piezo warning beeps, and a sharp discharge snap.

The first beep is the cue: it must land at 90% charge (full damage). sound.py writes the cue's time into
../assets/warning.json and build.py delays the sound so the cue lands 2.5 s into the charge; the beeps run for
ALARM_S and the snap follows them.

    python sound.py              -> ../assets/warning.wav + ../assets/warning.json (the released take)
    python sound.py --preview    -> warning_preview.wav (does not touch the assets)

Needs numpy, scipy and pyloudnorm. Everything is synthesised; nothing is sampled."""
import json, os, sys, wave
import numpy as np
import pyloudnorm as pyln
from scipy.signal import butter, sosfilt

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), 'assets')

RATE = 48000
LENGTH_S, SNAP_S = 1.00, 0.93        # total length; when the snap hits
PITCH = 2 ** (-7 / 12)               # 7 semitones below the hum's 50 -> 75 Hz starting design
GROWL = 1.0                          # detuned growl layer, harder drive, denser crackle and a thump under the snap
SEED = 202                           # the chosen take

# The warning beeps: fast, clean piezo beeping in the last ALARM_S before the snap.
ALARM_S = 0.32
BEEP_HZ, BEEP_ON_S, BEEP_GAP_S, BEEP_HARMONICS = 2900.0, 0.045, 0.025, 2
BEEP_GAIN = 1.3                      # beeps against the hum; the hum dips by BEEP_DUCK under each beep
BEEP_DUCK = 0.5

# In-game audibility: the game's own railgun rumble masks sub-bass, so the hum starts strong (HUM_FLOOR of its final
# level), its sub-bass is cut and its weight pushed into the 150 Hz - 1 kHz growl range. TARGET_LUFS puts the
# charge-up at the old coil-charge sound's in-game level (-7 to -8 LUFS) with the beeps above it.
HUM_FLOOR = 0.9
BODY_GAIN = 3.0
TARGET_LUFS = -6.5
PEAK = 0.89


def seconds(n):
    return np.arange(n) / RATE


def envelope(n, attack=0.003, release=0.03):
    e = np.ones(n)
    a, r = max(1, int(attack * RATE)), int(release * RATE)
    e[:a] = np.linspace(0, 1, a) ** 2
    e[-r:] *= np.linspace(1, 0, r) ** 2
    return e


def phase(freq, n):
    f = freq if np.ndim(freq) else np.full(n, float(freq))
    return 2 * np.pi * np.cumsum(f) / RATE


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, min(hi, RATE * 0.45)], 'bp', fs=RATE, output='sos'), x)


def hp(x, cutoff, order=2, axis=-1):
    return sosfilt(butter(order, cutoff, 'hp', fs=RATE, output='sos'), x, axis=axis)


def arcing(n, per_second, amount, rng, lo, hi):
    """Electric crackle: short bursts of filtered noise at random moments, scaled by `amount` over time."""
    out, t = np.zeros(n), 0
    while True:
        t += int(rng.exponential(RATE / per_second))
        if t >= n:
            break
        m = int(rng.uniform(0.002, 0.012) * RATE)
        burst = rng.standard_normal(m) * np.exp(-seconds(m) / 0.003) * rng.uniform(0.3, 1)
        out[t:t + m] += burst[:n - t] * amount[t]
    return bp(out, lo, hi)


def room(stereo, rng, wet=0.1, time=0.15):
    n = int(time * RATE)
    out = stereo.copy()
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-seconds(n) / (time / 5))
        ir /= np.sqrt((ir ** 2).sum())
        out[:, ch] += wet * np.convolve(stereo[:, ch], ir)[:len(stereo)]
    return out


def widen(mono, samples):
    return np.stack([mono, np.concatenate([np.zeros(samples), mono[:-samples]])], 1)


def master(stereo):
    s = hp(stereo, 80, axis=0)
    s = sosfilt(butter(4, 15000, 'lp', fs=RATE, output='sos'), s, axis=0)
    fade = int(0.004 * RATE)
    s[-fade:] *= np.linspace(1, 0, fade)[:, None]
    meter = pyln.Meter(RATE, block_size=0.2)
    for _ in range(10):                  # level to the target loudness, soft-limit any peaks
        s *= 10 ** ((TARGET_LUFS - meter.integrated_loudness(s)) / 20)
        if np.abs(s).max() > PEAK:
            s = np.tanh(s / PEAK) * PEAK
    return s


def beep_starts():
    """Start time (s) of every warning beep; the first one is the cue."""
    starts, at = [], SNAP_S - ALARM_S
    while at + BEEP_ON_S <= SNAP_S - 0.005:
        starts.append(at)
        at += BEEP_ON_S + BEEP_GAP_S
    return starts


def beeps(n):
    out = np.zeros(n)
    m = int(BEEP_ON_S * RATE)
    ph = phase(BEEP_HZ, m)
    tone = sum(np.sin(h * ph) / h ** 1.5 for h in range(1, 2 * BEEP_HARMONICS, 2)) * envelope(m, 0.002, 0.004)
    for at in beep_starts():
        i = int(at * RATE)
        out[i:i + m] += tone[:n - i]
    return out


def arcing_surge(rng):
    n, end = int(LENGTH_S * RATE), SNAP_S
    t = seconds(n)
    swell = np.clip(t / end, 0, 1) ** 2
    f = 50 * PITCH * (1 + 0.5 * swell)                                       # the hum climbs half an octave
    hum = sum(np.sin(k * phase(f, n)) / k for k in range(1, 12)) * (1 - 0.6 * np.exp(-t / 0.15))
    hum += GROWL * sum(np.sin(k * phase(f * 1.03, n) + 1.0) / k for k in range(1, 12))  # detuned growl, beating
    hum = hp(np.tanh((2.5 + 3 * GROWL) * hum), max(60, 120 * PITCH))                    # buzzy, mains-like
    fizz = bp(rng.standard_normal(n), 2000 * PITCH, 7000 * PITCH) * (0.5 + 0.5 * np.sin(phase(2 * f, n))) ** 6 * swell * 0.4
    arcs = arcing(n, 90 + 80 * GROWL, np.clip((t - 0.2) / (end - 0.2), 0, 1) ** 1.5,
                  np.random.default_rng(rng.integers(1 << 30)), 1500 * PITCH, 11000 * PITCH) * (1.1 + 0.5 * GROWL)

    out = hum * 0.7 * (HUM_FLOOR + (1 - HUM_FLOOR) * swell) + fizz + arcs
    out = hp(out, 90, order=4)                                               # cut the masked sub-bass
    out += 0.8 * bp(out, 150, 1000)                                          # push the growl where it's heard
    out *= BODY_GAIN
    b = beeps(n)
    out = out * (1 - BEEP_DUCK * (np.abs(b) > 1e-3)) + b * BEEP_GAIN
    out *= (t < end)
    e = int(end * RATE)
    out[:e] *= envelope(e, 0.05, 0.004)

    m = n - e                                                                # the discharge snap
    tm = seconds(m)
    snap = bp(rng.standard_normal(m), 1200 * PITCH, 12000 * PITCH) * np.exp(-tm / 0.008) * 3.5
    snap += np.sin(phase(np.linspace(900 * PITCH, 120 * PITCH, m), m)) * np.exp(-tm / 0.02) * 0.8
    snap += np.sin(phase(np.linspace(140, 70, m), m)) * np.exp(-tm / 0.04) * 1.2 * GROWL   # thump under it
    out[e:] += snap
    return master(room(widen(out, 30), rng))


def render():
    out = arcing_surge(np.random.default_rng(SEED))
    return np.clip(np.round(out * 32767), -32768, 32767).astype('<i2')


def write_wav(path, pcm):
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm.tobytes())


if __name__ == '__main__':
    pcm = render()
    length = pcm.shape[0] / RATE
    if '--preview' in sys.argv:
        write_wav('warning_preview.wav', pcm)
        print('warning_preview.wav', length, 's')
    else:
        write_wav(os.path.join(ASSETS, 'warning.wav'), pcm)
        cue = int(beep_starts()[0] * RATE) / RATE                            # sample-exact start of the first beep
        with open(os.path.join(ASSETS, 'warning.json'), 'w') as f:
            json.dump({'cue_s': cue, 'cue': 'first warning beep', 'length_s': length, 'beeps_s': [round(b, 6) for b in beep_starts()],
                       'beep_s': BEEP_ON_S, 'snap_s': SNAP_S}, f, indent=2)
        print('assets/warning.wav', length, 's; cue (lands at 90% charge):', cue, 's into the sound')
