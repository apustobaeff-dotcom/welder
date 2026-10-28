"""Soundtrack for the 75 s ARCUS video: 120 BPM, D minor, every cut on a bar line.
Pure numpy synthesis; writes work/music.wav (44.1 kHz stereo, 16-bit)."""
import numpy as np, wave, sys

SR = 44100
DUR = 75.0
BPM = 120
BEAT = 60 / BPM          # 0.5 s
BAR = BEAT * 4           # 2.0 s
N = int(SR * DUR)
t_all = np.arange(N) / SR
rng = np.random.default_rng(7)

def note(m):  # midi -> Hz
    return 440.0 * 2 ** ((m - 69) / 12)

def env_adsr(n, a, d, s, r, sr=SR):
    e = np.ones(n) * s
    A, D, R = int(a * sr), int(d * sr), int(r * sr)
    A = min(A, n); e[:A] = np.linspace(0, 1, A, endpoint=False)
    D = min(D, n - A); e[A:A + D] = np.linspace(1, s, D, endpoint=False)
    if R > 0 and R < n: e[-R:] *= np.linspace(1, 0, R)
    return e

def add(buf, start, sig):
    i = int(round(start * SR))
    if i >= len(buf): return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[:j - i]

def lowpass(x, cutoff):
    # FFT brick-ish lowpass with soft rolloff
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))

def highpass(x, cutoff):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 - 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))

def reverb(x, secs=2.4, mix=0.25, seed=1):
    n = int(secs * SR)
    r = np.random.default_rng(seed)
    ir = r.standard_normal(n) * np.exp(-np.linspace(0, 6.5, n))
    ir = lowpass(np.pad(ir, (0, 0)), 5000)
    ir /= np.sqrt(np.sum(ir ** 2))
    L = len(x) + n
    nfft = 1 << (L - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[:len(x)]
    return x * (1 - mix) + y * mix

# ---------- arrangement intensity per section (bar-aligned) ----------
CUTS = [0, 4, 10, 18, 24, 26, 34, 44, 50, 58, 66, 70]
def section(t):
    for k in range(len(CUTS) - 1, -1, -1):
        if t >= CUTS[k]: return k
    return 0
# 0 hook,1 reveal,2 group,3 supply,4 divider,5 roadmap,6 tests,7 products,8 perechen,9 joint,10 support,11 outro
DRUMS = {0: 0, 1: 0.6, 2: 1, 3: 1, 4: 0, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1, 11: 0}
HATS = {0: 0, 1: 0, 2: 0.7, 3: 0.8, 4: 0, 5: 0.8, 6: 1, 7: 0.9, 8: 0.9, 9: 1, 10: 0.8, 11: 0}
BASS = {0: 0.0, 1: 0.7, 2: 1, 3: 1, 4: 0.4, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1, 11: 0}

# chord roots per bar: Dm, Bb, F, C  (midi)
PROG = [(50, [62, 65, 69]), (46, [62, 65, 70]), (41, [60, 65, 69]), (48, [60, 64, 67])]

pad = np.zeros(N); bass = np.zeros(N); kick = np.zeros(N); hats = np.zeros(N); fx = np.zeros(N); lead = np.zeros(N)

# ---------- pad ----------
nbars = int(np.ceil(DUR / BAR))
for b in range(nbars):
    st = b * BAR
    root, chord = PROG[b % 4]
    if st >= 70:  # final: hold Dm to the end
        root, chord = PROG[0]
    length = BAR + 0.6 if st < 70 else DUR - st
    n = int(length * SR)
    tt = np.arange(n) / SR
    sig = np.zeros(n)
    for m in chord + [root + 12]:
        f = note(m)
        for k, amp in [(1, 1), (2, .35), (3, .18), (4, .08)]:
            det = 1 + (rng.random() - .5) * 0.004
            sig += amp * np.sin(2 * np.pi * f * k * det * tt + rng.random() * 6.28)
    e = env_adsr(n, 0.35, 0.4, 0.8, 0.6)
    add(pad, st, sig * e * 0.05)
    if st >= 70: break
pad = lowpass(pad, 2200)

# ---------- bass: 8th-note pulse ----------
for b in range(nbars):
    st = b * BAR
    root = PROG[b % 4][0] - 12
    for i in range(8):
        t0 = st + i * BEAT / 2
        lvl = BASS[section(t0)]
        if lvl == 0 or t0 >= 70: continue
        n = int(0.24 * SR); tt = np.arange(n) / SR
        f = note(root)
        sig = np.sin(2 * np.pi * f * tt) + 0.4 * np.sin(2 * np.pi * 2 * f * tt) + 0.15 * np.sign(np.sin(2 * np.pi * f * tt))
        e = np.exp(-tt * 11) * (1 - np.exp(-tt * 300))
        acc = 1.0 if i % 2 == 0 else 0.7
        add(bass, t0, sig * e * 0.16 * lvl * acc)
bass = lowpass(bass, 700)
# hook bass: one sustained sub on D
n = int(4 * SR); tt = np.arange(n) / SR
add(bass, 0, np.sin(2 * np.pi * note(38) * tt) * env_adsr(n, 0.02, 0.5, 0.6, 1.2) * 0.22)

# ---------- kick on beats 1 & 3, 4-on-floor in high sections ----------
def kick_hit(level):
    n = int(0.42 * SR); tt = np.arange(n) / SR
    f = 46 + 90 * np.exp(-tt * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-tt * 7.5) * level
t = 0.0
while t < DUR:
    lvl = DRUMS[section(t)]
    beat_in_bar = int(round((t % BAR) / BEAT))
    if lvl > 0 and t < 70:
        four = section(t) in (6, 9)
        if beat_in_bar in (0, 2) or four:
            add(kick, t, kick_hit(0.42 * lvl * (1 if beat_in_bar in (0, 2) else .75)))
    t += BEAT

# ---------- hats: off-beat 8ths, metallic, in the background ----------
def hat(level, length=0.06):
    n = int(length * SR); tt = np.arange(n) / SR
    s = rng.standard_normal(n)
    # metallic partials
    for f in (6100, 7350, 8800):
        s += 0.6 * np.sign(np.sin(2 * np.pi * f * tt))
    return s * np.exp(-tt * 70) * level
t = BEAT / 2
while t < DUR:
    lvl = HATS[section(t)]
    if lvl > 0 and t < 70:
        add(hats, t, hat(0.018 * lvl))
    t += BEAT
hats = highpass(hats, 5000)

# ---------- anvil hits on scene cuts (tuned to D) ----------
def anvil(level):
    n = int(2.2 * SR); tt = np.arange(n) / SR
    f0 = note(62)
    s = np.zeros(n)
    for ratio, amp, dec in [(1, 1, 3.2), (2.0, .5, 4), (2.76, .45, 5), (4.0, .25, 6), (5.4, .2, 8)]:
        s += amp * np.sin(2 * np.pi * f0 * ratio * tt) * np.exp(-tt * dec)
    boom = np.sin(2 * np.pi * note(38) * tt) * np.exp(-tt * 5) * 1.2
    click = rng.standard_normal(n) * np.exp(-tt * 120) * 0.3
    return (s * 0.5 + boom + click) * level
for c in CUTS[1:]:
    add(fx, c, anvil(0.10 if c not in (24, 70) else 0.16))
add(fx, 0.0, anvil(0.12))

# ---------- soft tonal ticks on UI events (D major-pentatonic over Dm: D, F, A) ----------
def tick(m, level=0.05):
    n = int(0.5 * SR); tt = np.arange(n) / SR
    f = note(m)
    return (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt)) * np.exp(-tt * 9) * (1 - np.exp(-tt * 400)) * level
for i, tt0 in enumerate([28.5, 29.0, 29.5, 30.0]):
    add(lead, tt0, tick([74, 77, 81, 86][i], 0.06))
for i, tt0 in enumerate([60.5, 61.0, 61.5, 62.0]):
    add(lead, tt0, tick([86, 81, 77, 74][i], 0.05))
for i, tt0 in enumerate([10.5, 11.0, 11.5, 12.0]):
    add(lead, tt0, tick([74, 77, 81, 84][i], 0.035))
for i, tt0 in enumerate([18.5, 19.0, 19.5, 20.0, 20.5, 21.0, 21.5, 22.0]):
    add(lead, tt0, tick([74, 77, 81, 84][i % 4] + (12 if i >= 4 else 0), 0.028))
for i, tt0 in enumerate([44.5, 45.0, 45.5, 46.0]):
    add(lead, tt0, tick([69, 74, 77, 81][i], 0.035))
add(lead, 54.5, tick(86, 0.06))  # cursor click
for i, tt0 in enumerate([35.0, 35.5, 36.0]):
    add(lead, tt0, tick([74, 77, 81][i], 0.03))

# ---------- risers into the divider (24) and finale (70) ----------
def riser(length, level):
    n = int(length * SR); tt = np.arange(n) / SR
    s = rng.standard_normal(n)
    s = lowpass(highpass(s, 1200), 5000)
    return s * (tt / length) ** 2.2 * level
add(fx, 22.0, riser(2.0, 0.022))
add(fx, 68.0, riser(2.0, 0.026))
add(fx, 32.0, riser(2.0, 0.014))

# ---------- mix ----------
mix_dry = pad * 1.0 + bass * 1.0 + kick * 1.0
wet_send = pad * 1.0 + lead * 1.0 + fx * 1.0 + hats * 0.6
wet = reverb(wet_send, 2.6, 0.35)
mix = mix_dry + wet
# gentle sidechain-ish duck of pad under kick
mix = mix
# fade in/out
fi = int(0.05 * SR); mix[:fi] *= np.linspace(0, 1, fi)
fo = int(1.2 * SR); mix[-fo:] *= np.linspace(1, 0, fo) ** 1.5
mix = np.tanh(mix * 1.4) / np.tanh(1.4)
mix /= np.max(np.abs(mix)) / 0.89
# stereo widen: slight delay on the right for reverb-ish width
L = mix
Rch = np.concatenate([np.zeros(int(0.007 * SR)), wet[:-int(0.007 * SR)] * 0.15]) + mix * 0.92
st = np.stack([L, Rch], axis=1)
st = st / np.max(np.abs(st)) * 0.89
out = (st * 32767).astype(np.int16)
with wave.open(sys.argv[1], 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(out.tobytes())
print('ok', out.shape[0] / SR, 's')
