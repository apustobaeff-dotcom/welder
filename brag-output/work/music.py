# 60 s soundtrack: 120 BPM, D minor (Dm-Bb-F-C), SFX on the same grid.
import numpy as np, wave
SR = 48000; DUR = 60.0; N = int(SR * DUR)
BPM = 120; BEAT = 60 / BPM; BAR = 4 * BEAT; S16 = BEAT / 4
rng = np.random.default_rng(7)
def tt(n): return np.arange(n) / SR
def mtof(m): return 440 * 2 ** ((m - 69) / 12)
L = np.zeros(N); R = np.zeros(N); SEND = np.zeros(N)  # reverb send (mono)

def add(sig, t0, gain=1.0, pan=0.0, send=0.0):
    i = int(round(t0 * SR));
    if i >= N: return
    sig = sig[:N - i]
    l = np.cos((pan + 1) * np.pi / 4); r = np.sin((pan + 1) * np.pi / 4)
    L[i:i + len(sig)] += sig * gain * l * 1.414; R[i:i + len(sig)] += sig * gain * r * 1.414
    SEND[i:i + len(sig)] += sig * gain * send

def env(n, a, d, s=0.0, rel=None):
    t = tt(n); e = np.minimum(1, t / max(a, 1e-4))
    e = e * (s + (1 - s) * np.exp(-np.maximum(0, t - a) / max(d, 1e-4)))
    return e

def lp1(x, fc):  # one-pole lowpass
    a = np.exp(-2 * np.pi * fc / SR); y = np.empty_like(x); z = 0.0
    for i in range(len(x)): z = (1 - a) * x[i] + a * z; y[i] = z
    return y

def lp_fft(x, fc):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / fc) ** 4); return np.fft.irfft(X, len(x))

def bp_fft(x, lo, hi):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= (1 / np.sqrt(1 + (lo / np.maximum(f, 1)) ** 4)) * (1 / np.sqrt(1 + (f / hi) ** 4)); return np.fft.irfft(X, len(x))

# --- harmony
D = 62  # D4
CH = {'Dm': [50, 57, 62, 65, 69], 'Bb': [46, 53, 58, 62, 65], 'F': [41, 53, 57, 60, 65], 'C': [48, 55, 60, 64, 67]}
ROOT = {'Dm': 38, 'Bb': 34, 'F': 41, 'C': 36}
PROG = ['Dm', 'Bb', 'F', 'C']
def chord_at(bar):
    if bar < 2: return 'Dm'
    if bar >= 28: return 'Dm'
    return PROG[(bar - 2) % 4]

# --- instruments
def pad(notes, dur, bright=1.0):
    n = int(dur * SR); t = tt(n); s = np.zeros(n)
    for m in notes:
        for det in (-0.08, 0.0, 0.07):
            f = mtof(m + det); ph = rng.random() * 6.28
            s += (np.sin(2 * np.pi * f * t + ph) + 0.35 * np.sin(4 * np.pi * f * t + ph) * bright + 0.12 * np.sin(6 * np.pi * f * t) * bright)
    a = np.minimum(1, t / 0.6) * np.minimum(1, (dur - t) / 0.5)
    return lp_fft(s * a, 2200 * bright + 400) / (len(notes) * 3)

def bass(m, dur):
    n = int(dur * SR); t = tt(n); f = mtof(m)
    s = np.sin(2 * np.pi * f * t) + 0.5 * np.tanh(3 * np.sin(2 * np.pi * f * t)) * 0.6
    e = np.minimum(1, t / 0.004) * np.exp(-t / (dur * 0.9)) * np.minimum(1, (dur - t) / 0.01)
    return lp_fft(s * e, 500)

def kick():
    n = int(0.45 * SR); t = tt(n)
    f = 45 + 110 * np.exp(-t / 0.035); ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t / 0.18) + 0.15 * rng.standard_normal(n) * np.exp(-t / 0.004)

def hat(open_=False):
    n = int((0.25 if open_ else 0.06) * SR); x = rng.standard_normal(n)
    x = bp_fft(x, 7000, 14000); return x * np.exp(-tt(n) / (0.08 if open_ else 0.018))

def clap():
    n = int(0.35 * SR); x = bp_fft(rng.standard_normal(n), 900, 5000); t = tt(n)
    e = np.exp(-t / 0.12) * (1 + 0.6 * ((t % 0.012) < 0.004) * (t < 0.03)); return x * e

def pluck(m, dur=0.4, bright=3000):
    n = int(dur * SR); t = tt(n); f = mtof(m)
    s = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.sin(2 * np.pi * f * t)
    return lp_fft(s * np.exp(-t / 0.09), bright) * np.minimum(1, t / 0.002)

def bell(m, dur=1.6):
    n = int(dur * SR); t = tt(n); f = mtof(m)
    s = np.sin(2 * np.pi * f * t + 1.2 * np.sin(2 * np.pi * f * 3.5 * t) * np.exp(-t / 0.3))
    return s * np.exp(-t / 0.5) * np.minimum(1, t / 0.003)

def impact(big=False):
    n = int((2.5 if big else 1.2) * SR); t = tt(n)
    f = mtof(26) + mtof(38) * np.exp(-t / 0.06); ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) * np.exp(-t / (0.8 if big else 0.35))
    s += 0.25 * lp_fft(rng.standard_normal(n), 300) * np.exp(-t / 0.15)
    return s

def whoosh(dur=0.5, up=True):
    n = int(dur * SR); t = tt(n); x = rng.standard_normal(n)
    # sweep via crossfaded bandpasses
    out = np.zeros(n); K = 8
    for k in range(K):
        c = 400 * (16 ** (k / (K - 1)))
        w = np.exp(-((t / dur - (k / (K - 1) if up else 1 - k / (K - 1))) ** 2) / 0.03)
        out += bp_fft(x, c * 0.7, c * 1.4) * w
    e = (t / dur) ** 2 if up else (1 - t / dur) ** 2
    return out * e

def riser(dur):
    n = int(dur * SR); t = tt(n); x = bp_fft(rng.standard_normal(n), 1500, 9000)
    return x * (t / dur) ** 3

def crackle(dur):
    n = int(dur * SR); s = np.zeros(n)
    k = rng.random(n) < 0.0025
    s[k] = rng.standard_normal(k.sum())
    s = bp_fft(s, 2500, 12000)
    return s

# --- arrangement
bars = int(DUR / BAR)
for b in range(bars):
    t0 = b * BAR; ch = chord_at(b)
    if b < 28:
        bright = 0.5 if b < 6 else (0.8 if b < 12 else 1.0)
        add(pad(CH[ch], BAR + 0.5, bright), t0, 0.22 if b >= 2 else 0.18, 0, 0.5)
    # bass 8ths from bar 2
    if 2 <= b < 28:
        for k in range(8):
            m = ROOT[ch] + (12 if k in (3, 7) and b >= 6 else 0)
            add(bass(m, BEAT / 2 * 0.9), t0 + k * BEAT / 2, 0.34 if k % 2 == 0 else 0.24)
    # drums
    if 2 <= b < 28:
        for q in range(4):
            if not (b in (21,) and q >= 2):  # small gap before joint build? keep
                add(kick(), t0 + q * BEAT, 0.62)
        for s16 in range(16):
            if b >= 6 or s16 % 2 == 0:
                g = 0.05 if s16 % 4 == 2 else 0.028
                add(hat(), t0 + s16 * S16, g, 0.25 * (1 if s16 % 2 else -1))
        if b >= 12:
            add(clap(), t0 + BEAT, 0.16, 0, 0.25); add(clap(), t0 + 3 * BEAT, 0.16, 0, 0.25)
        if b >= 6:
            add(hat(True), t0 + 3.5 * BEAT, 0.03, 0.3)
    # arp 16ths from bar 6
    if 6 <= b < 28:
        notes = sorted(CH[ch][1:]) ; pat = [0, 1, 2, 3, 2, 1, 3, 2]
        for s16 in range(16):
            m = notes[pat[s16 % 8] % len(notes)] + 12
            add(pluck(m, 0.3, 2500 if b < 12 else 4000), t0 + s16 * S16, 0.05, 0.35 * np.sin(s16), 0.35)

# hook: drone + crackle + riser into 4s
n = int(4.2 * SR); t = tt(n)
drone = (np.sin(2 * np.pi * mtof(26) * t) + 0.5 * np.sin(2 * np.pi * mtof(38) * t)) * np.minimum(1, t / 1.5)
add(drone, 0, 0.22)
add(crackle(12.0) * np.concatenate([np.ones(int(10 * SR)), np.linspace(1, 0, int(2 * SR))]), 0, 0.10, 0.2)
arc = lp_fft(rng.standard_normal(int(12 * SR)), 180) * (1 + 0.5 * np.sin(2 * np.pi * 100 * tt(int(12 * SR))))
add(arc * np.minimum(1, tt(len(arc)) / 0.5) * np.minimum(1, (12 - tt(len(arc))) / 1.5), 0, 0.12, 0, 0.1)
add(riser(2.0), 2.0, 0.10, 0, 0.3)
add(impact(), 0.0, 0.35, 0, 0.4)
add(bell(74, 2.5), 0.5, 0.06, -0.2, 0.6)  # D5 on "От К54"
add(impact(), 4.0, 0.45, 0, 0.4)

# cuts
CUTS = [12, 18, 24, 32, 38, 44, 50, 56]
for c in CUTS:
    add(whoosh(0.5), c - 0.5, 0.08, 0.0, 0.3)
    add(impact(big=c in (24, 44, 56)), c, 0.5 if c in (24, 44, 56) else 0.32, 0, 0.35)
    add(clap() * 0.0, c, 0)
add(riser(4.0), 40.0, 0.11, 0, 0.3)   # build into 44
add(riser(2.0), 22.0, 0.07, 0, 0.3)   # into 24

# UI accents, all on grid, in key
for i, m in enumerate([74, 77, 81, 86]): add(bell(m, 1.2), 12.25 + i * 0.25, 0.035, -0.4 + i * 0.27, 0.5)   # plant cards
add(bell(69, 1.5), 14.0, 0.04, 0, 0.5)
for i, m in enumerate([62, 65, 69, 74]): add(bell(m + 12, 1.2), 18.5 + i * 1.0, 0.04, -0.3 + i * 0.2, 0.5)  # chain nodes
for i, m in enumerate([74, 77, 81, 86]): add(bell(m, 1.6), 25.0 + i * 1.0, 0.05, -0.2 + i * 0.13, 0.55)   # Перечень № 1 x4
add(bell(74, 2.0), 29.0, 0.05, 0, 0.6); add(bell(81, 2.0), 29.0, 0.035, 0, 0.6)
for i in range(6): add(pluck(74 + [0, 3, 7, 12, 15, 19][i], 0.25, 5000), 38.5 + i * 0.25, 0.05, 0, 0.4)  # weld layers
for i in range(10): add(bell(86 + [0, 3, 5, 7, 10, 12, 15, 17, 19, 22][i] - 12, 0.6), 45.75 + i * 0.125, 0.018, -0.5 + i * 0.1, 0.4)  # chips
for i in range(10): add(hat(), 44.125 + i * 0.125, 0.04, 0.2)  # 59 counter ticks
for i, m in enumerate([62, 65, 69, 74]): add(bell(m + 12, 1.2), 50.5 + i * 0.5, 0.04, -0.3 + i * 0.2, 0.5)  # steps
# outro: final chord
add(pad([38, 50, 57, 62, 65, 69, 74], 4.2, 1.0), 56.0, 0.34, 0, 0.7)
add(bass(26, 3.5) , 56.0, 0.5)
add(bell(74, 3.5), 56.0, 0.07, -0.2, 0.7); add(bell(81, 3.5), 56.25, 0.05, 0.2, 0.7)

# --- reverb (FFT convolution with decaying stereo noise IR)
def ir(sec, seed):
    r = np.random.default_rng(seed); n = int(sec * SR); t = tt(n)
    x = r.standard_normal(n) * np.exp(-t / (sec / 6.5)); x = lp_fft(x, 6000); x[:int(0.012 * SR)] = 0; return x / np.sqrt((x ** 2).sum())
def conv(x, h):
    m = len(x) + len(h); nfft = 1 << (m - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:len(x)]
rl = conv(SEND, ir(2.4, 1)); rr = conv(SEND, ir(2.4, 2))
L += rl * 0.55; R += rr * 0.55

# master: gentle low-cut, soft clip, fade
mix = np.stack([L, R])
for k in range(2): mix[k] = mix[k] - lp_fft(mix[k], 25)
fade = np.ones(N); fn = int(0.7 * SR); fade[-fn:] = np.linspace(1, 0, fn) ** 2
mix *= fade
pk = np.abs(mix).max(); mix = mix / pk * 1.25
mix = np.tanh(mix) / np.tanh(1.25) * 0.89
pcm = (mix.T * 32767).astype(np.int16)
with wave.open('music.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print('ok', pk)
