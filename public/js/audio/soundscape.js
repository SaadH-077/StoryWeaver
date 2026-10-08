// Procedural soundscape: every ambience bed and sound effect is synthesised live with the Web Audio API.
// No audio files, no licences, endless non-repeating variation — and the story agents control it through a
// small vocabulary (kept in sync with AMBIENCE / SFX in src/storyweaver/schemas.py).

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

export const AMBIENCE = ["rain", "storm", "wind", "ocean", "river", "fire", "night", "forest",
  "city", "machine", "space", "cave", "underwater", "magic"];

export class Soundscape {
  constructor(engine) {
    this.e = engine;
    this.c = engine.ctx;
    this.layers = new Map();
    this.noise = {
      white: this._noise((x) => x),
      pink: this._pinkNoise(),
      brown: this._brownNoise(),
    };
  }

  // ---------------------------------------------------------------- noise sources
  _noise(shape, seconds = 6) {
    const len = this.c.sampleRate * seconds;
    const buf = this.c.createBuffer(1, len, this.c.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = shape(Math.random() * 2 - 1);
    return buf;
  }
  _pinkNoise() { // Paul Kellet's refined method
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    return this._noise((w) => {
      b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759;
      b2 = 0.969 * b2 + w * 0.153852; b3 = 0.8665 * b3 + w * 0.3104856;
      b4 = 0.55 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.016898;
      const out = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
      b6 = w * 0.115926;
      return out;
    });
  }
  _brownNoise() {
    let last = 0;
    return this._noise((w) => { last = (last + 0.02 * w) / 1.02; return last * 3.5; });
  }
  src(kind) {
    const s = this.c.createBufferSource();
    s.buffer = this.noise[kind];
    s.loop = true;
    s.start(0, rand(0, 5));
    this._collect?.push(s); // continuous sources are stopped when their layer is removed
    return s;
  }
  filter(type, freq, q = 0.7) {
    const f = this.c.createBiquadFilter();
    f.type = type; f.frequency.value = freq; f.Q.value = q;
    return f;
  }
  gain(v) { const g = this.c.createGain(); g.gain.value = v; return g; }
  lfo(rate, depth, param) {
    const o = this.c.createOscillator();
    o.frequency.value = rate;
    const g = this.gain(depth);
    o.connect(g).connect(param);
    o.start();
    this._collect?.push(o);
    return o;
  }
  chain(...nodes) { nodes.reduce((a, b) => a.connect(b)); return nodes[nodes.length - 1]; }

  /** Run `fn(time)` at random intervals (seconds) while the layer lives; returns a stopper. */
  every(min, max, fn) {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      if (this.c.state === "running") fn(this.c.currentTime + 0.05);
      setTimeout(tick, rand(min, max) * 1000);
    };
    setTimeout(tick, rand(min, max) * 500);
    return () => { alive = false; };
  }

  // one-shot helpers
  burst(time, { dur = 0.02, type = "highpass", freq = 2000, q = 0.7, level = 0.1, noise = "white", dest }) {
    const s = this.c.createBufferSource();
    s.buffer = this.noise[noise];
    const f = this.filter(type, freq, q);
    const g = this.gain(0);
    g.gain.setValueAtTime(level, time);
    g.gain.exponentialRampToValueAtTime(0.0001, time + dur);
    s.connect(f).connect(g).connect(dest);
    s.start(time, rand(0, 4));
    s.stop(time + dur + 0.05);
  }
  tone(time, { freq = 880, to = null, dur = 0.5, type = "sine", level = 0.05, attack = 0.005, dest, reverb = false }) {
    const o = this.c.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, time);
    if (to) o.frequency.exponentialRampToValueAtTime(to, time + dur * 0.9);
    const g = this.gain(0);
    g.gain.setValueAtTime(0.0001, time);
    g.gain.exponentialRampToValueAtTime(level, time + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, time + dur);
    o.connect(g).connect(dest);
    if (reverb) g.connect(this.e.reverb);
    o.start(time);
    o.stop(time + dur + 0.05);
  }

  // ---------------------------------------------------------------- ambience recipes
  recipes() {
    const R = {};
    R.rain = (out, k) => {
      const hiss = this.chain(this.src("pink"), this.filter("highpass", 450), this.filter("lowpass", 7500), this.gain(0.32 * k));
      hiss.connect(out);
      const drops = this.every(0.03, 0.14, (t) => this.burst(t, { dur: rand(0.01, 0.03), type: "bandpass", freq: rand(2200, 5200), q: 6, level: rand(0.02, 0.07) * k, dest: out }));
      return () => drops();
    };
    R.wind = (out, k) => {
      const bp = this.filter("bandpass", 520, 0.6);
      const g = this.gain(0.5 * k);
      this.chain(this.src("brown"), bp, g).connect(out);
      const l1 = this.lfo(rand(0.05, 0.09), 260, bp.frequency);
      const l2 = this.lfo(rand(0.09, 0.14), 0.22 * k, g.gain);
      return () => { l1.stop(); l2.stop(); };
    };
    R.storm = (out, k) => {
      const a = R.rain(out, Math.min(1.3, k * 1.25));
      const b = R.wind(out, k);
      const thunder = this.every(14, 30, (t) => this.sfxAt("thunder", t, 0.55));
      return () => { a(); b(); thunder(); };
    };
    R.ocean = (out, k) => {
      const swell = this.gain(0.35 * k);
      this.chain(this.src("brown"), this.filter("lowpass", 900), swell).connect(out);
      const foam = this.gain(0.06 * k);
      this.chain(this.src("pink"), this.filter("highpass", 1800), foam).connect(out);
      const rate = rand(0.07, 0.11);
      const l1 = this.lfo(rate, 0.3 * k, swell.gain);
      const l2 = this.lfo(rate, 0.05 * k, foam.gain);
      return () => { l1.stop(); l2.stop(); };
    };
    R.river = (out, k) => {
      this.chain(this.src("pink"), this.filter("bandpass", 1100, 0.5), this.gain(0.22 * k)).connect(out);
      const babble = this.gain(0.04 * k);
      const bp = this.filter("bandpass", 2800, 2.5);
      this.chain(this.src("white"), bp, babble).connect(out);
      const mod = this.every(0.08, 0.25, (t) => {
        babble.gain.setTargetAtTime(rand(0.01, 0.07) * k, t, 0.05);
        bp.frequency.setTargetAtTime(rand(1800, 3600), t, 0.08);
      });
      return () => mod();
    };
    R.fire = (out, k) => {
      this.chain(this.src("brown"), this.filter("lowpass", 260), this.gain(0.3 * k)).connect(out);
      const crackle = this.every(0.03, 0.22, (t) => this.burst(t, { dur: rand(0.004, 0.014), type: "highpass", freq: rand(1200, 3000), level: rand(0.04, 0.22) * k, dest: out }));
      return () => crackle();
    };
    R.night = (out, k) => {
      const wind = R.wind(out, 0.35 * k);
      const cricket = (freq) => this.every(0.55, 1.1, (t) => {
        for (let i = 0; i < 3; i++) this.tone(t + i * 0.045, { freq, dur: 0.03, level: 0.018 * k, attack: 0.004, dest: out });
      });
      const c1 = cricket(rand(4300, 4700));
      const c2 = cricket(rand(3800, 4200));
      return () => { wind(); c1(); c2(); };
    };
    R.forest = (out, k) => {
      const wind = R.wind(out, 0.3 * k);
      this.chain(this.src("pink"), this.filter("highpass", 3200), this.gain(0.025 * k)).connect(out);
      const birds = this.every(2.2, 6, (t) => {
        const base = rand(2400, 3600);
        const notes = Math.floor(rand(2, 5));
        for (let i = 0; i < notes; i++) {
          this.tone(t + i * rand(0.09, 0.16), { freq: base * rand(0.9, 1.15), to: base * rand(1.1, 1.4), dur: rand(0.06, 0.12), level: 0.022 * k, dest: out, reverb: true });
        }
      });
      return () => { wind(); birds(); };
    };
    R.city = (out, k) => {
      this.chain(this.src("brown"), this.filter("lowpass", 170), this.gain(0.42 * k)).connect(out);
      this.chain(this.src("pink"), this.filter("bandpass", 650, 0.6), this.gain(0.05 * k)).connect(out);
      const hum = this.c.createOscillator();
      hum.frequency.value = 55;
      this.chain(hum, this.filter("lowpass", 200), this.gain(0.018 * k)).connect(out);
      hum.start();
      // distant passing traffic swells
      const passes = this.every(5, 11, (t) => {
        const s = this.src("pink");
        const f = this.filter("bandpass", rand(300, 700), 0.8);
        const g = this.gain(0);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.07 * k, t + 1.6);
        g.gain.linearRampToValueAtTime(0, t + 3.4);
        s.connect(f).connect(g).connect(out);
        s.stop(t + 3.6);
      });
      return () => { hum.stop(); passes(); };
    };
    R.machine = (out, k) => {
      const lp = this.filter("lowpass", 300);
      const g = this.gain(0.05 * k);
      const oscs = [55, 55.4, 27.5].map((f, i) => {
        const o = this.c.createOscillator();
        o.type = i < 2 ? "sawtooth" : "sine";
        o.frequency.value = f;
        o.connect(lp);
        o.start();
        return o;
      });
      lp.connect(g).connect(out);
      const trem = this.lfo(6.5, 0.012 * k, g.gain);
      const ticks = this.every(0.45, 0.5, (t) => this.burst(t, { dur: 0.01, type: "bandpass", freq: 1800, q: 4, level: 0.025 * k, dest: out }));
      return () => { oscs.forEach((o) => o.stop()); trem.stop(); ticks(); };
    };
    R.space = (out, k) => {
      const lp = this.filter("lowpass", 600, 1.2);
      const g = this.gain(0.06 * k);
      const oscs = [55, 82.41, 110.3].map((f) => {
        const o = this.c.createOscillator();
        o.type = "triangle";
        o.frequency.value = f;
        o.connect(lp);
        o.start();
        return o;
      });
      lp.connect(g).connect(out);
      g.connect(this.e.reverb);
      const sweep = this.lfo(0.03, 280, lp.frequency);
      const stars = this.every(0.6, 2.2, (t) => this.tone(t, { freq: pick([1318.5, 1568, 1975.5, 2349.3, 2637]), dur: 2.4, level: 0.012 * k, attack: 0.02, dest: out, reverb: true }));
      return () => { oscs.forEach((o) => o.stop()); sweep.stop(); stars(); };
    };
    R.cave = (out, k) => {
      this.chain(this.src("brown"), this.filter("lowpass", 110), this.gain(0.28 * k)).connect(out);
      const drips = this.every(0.8, 3.2, (t) => {
        const f = rand(900, 1900);
        this.tone(t, { freq: f, to: f * 0.55, dur: 0.12, level: 0.05 * k, dest: out, reverb: true });
      });
      return () => drips();
    };
    R.underwater = (out, k) => {
      this.chain(this.src("brown"), this.filter("lowpass", 330), this.gain(0.4 * k)).connect(out);
      const bubbles = this.every(0.3, 1.6, (t) => {
        const n = Math.floor(rand(1, 4));
        for (let i = 0; i < n; i++) this.tone(t + i * rand(0.04, 0.1), { freq: rand(280, 420), to: rand(700, 1100), dur: 0.07, level: 0.04 * k, dest: out });
      });
      return () => bubbles();
    };
    R.magic = (out, k) => {
      const shimmer = this.gain(0.012 * k);
      this.chain(this.src("pink"), this.filter("bandpass", 6200, 3), shimmer).connect(out);
      const lfo = this.lfo(0.22, 0.009 * k, shimmer.gain);
      const bells = this.every(0.6, 2, (t) => this.tone(t, { freq: pick([1046.5, 1174.7, 1318.5, 1568, 1760, 2093]), dur: 1.8, level: 0.018 * k, attack: 0.01, dest: out, reverb: true }));
      return () => { lfo.stop(); bells(); };
    };
    return R;
  }

  /** Crossfade to a new set of ambience beds. */
  set(names, intensity = 0.6) {
    const wanted = new Set((names || []).filter((n) => AMBIENCE.includes(n)));
    const now = this.c.currentTime;
    for (const [name, layer] of this.layers) {
      if (!wanted.has(name)) {
        layer.out.gain.setTargetAtTime(0, now, 1.2);
        setTimeout(() => { layer.stop(); layer.out.disconnect(); }, 6000);
        this.layers.delete(name);
      }
    }
    const k = 0.75 + 0.5 * Math.min(1, Math.max(0, intensity));
    const recipes = this.recipes();
    for (const name of wanted) {
      if (this.layers.has(name)) continue;
      const out = this.gain(0);
      out.connect(this.e.ambBus);
      this._collect = [];
      const stopRecipe = recipes[name](out, k);
      const nodes = this._collect;
      this._collect = null;
      const stop = () => {
        stopRecipe();
        nodes.forEach((n) => { try { n.stop(); } catch { /* already stopped */ } });
      };
      out.gain.setTargetAtTime(1, now, 1.5);
      this.layers.set(name, { out, stop });
    }
  }

  // ---------------------------------------------------------------- sound effects
  sfx(name) { if (this.c.state === "running") this.sfxAt(name, this.c.currentTime + 0.02, 1); }

  sfxAt(name, t, level = 1) {
    const out = this.e.sfxBus;
    const L = level;
    switch (name) {
      case "thunder": {
        const s = this.src("brown");
        const f = this.filter("lowpass", 1800);
        const g = this.gain(0);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.9 * L, t + 0.08);
        g.gain.exponentialRampToValueAtTime(0.001, t + 4.2);
        f.frequency.setValueAtTime(1800, t);
        f.frequency.exponentialRampToValueAtTime(120, t + 3.5);
        s.connect(f).connect(g).connect(out);
        g.connect(this.e.reverb);
        s.stop(t + 4.5);
        break;
      }
      case "chime":
        [1, 2.01, 2.76].forEach((m, i) => this.tone(t + i * 0.02, { freq: 880 * m, dur: 2.2 - i * 0.4, level: 0.08 * L / (i + 1), dest: out, reverb: true }));
        break;
      case "bell":
        [1, 2, 3.01, 4.2].forEach((m, i) => this.tone(t, { freq: 523.25 * m, dur: 3.2 - i * 0.5, level: 0.09 * L / (i + 1.3), dest: out, reverb: true }));
        break;
      case "whoosh": {
        const s = this.src("white");
        const f = this.filter("bandpass", 300, 1.2);
        const g = this.gain(0);
        f.frequency.setValueAtTime(250, t);
        f.frequency.exponentialRampToValueAtTime(3200, t + 0.45);
        f.frequency.exponentialRampToValueAtTime(400, t + 0.9);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.35 * L, t + 0.4);
        g.gain.linearRampToValueAtTime(0, t + 0.95);
        s.connect(f).connect(g).connect(out);
        s.stop(t + 1);
        break;
      }
      case "heartbeat":
        for (let b = 0; b < 2; b++) {
          const base = t + b * 0.9;
          this.tone(base, { freq: 70, to: 42, dur: 0.16, level: 0.5 * L, dest: out });
          this.tone(base + 0.22, { freq: 62, to: 38, dur: 0.14, level: 0.38 * L, dest: out });
        }
        break;
      case "footsteps":
        for (let i = 0; i < 4; i++) this.burst(t + i * 0.42, { dur: 0.09, type: "lowpass", freq: 700 + i * 40, level: 0.35 * L, noise: "brown", dest: out });
        break;
      case "knock":
        for (let i = 0; i < 3; i++) {
          this.tone(t + i * 0.19, { freq: 190, to: 120, dur: 0.12, level: 0.35 * L, dest: out });
          this.burst(t + i * 0.19, { dur: 0.02, type: "bandpass", freq: 1200, q: 2, level: 0.12 * L, dest: out });
        }
        break;
      case "sparkle":
        [1568, 1760, 2093, 2349, 2637, 3136].forEach((f, i) => this.tone(t + i * 0.07, { freq: f, dur: 0.9, level: 0.03 * L, dest: out, reverb: true }));
        break;
      case "beep":
        [0, 0.16].forEach((d, i) => this.tone(t + d, { freq: i ? 1320 : 990, dur: 0.1, type: "square", level: 0.03 * L, dest: out }));
        break;
      case "splash": {
        this.burst(t, { dur: 0.6, type: "highpass", freq: 600, level: 0.4 * L, noise: "pink", dest: out });
        for (let i = 0; i < 5; i++) this.tone(t + 0.15 + i * rand(0.05, 0.12), { freq: rand(500, 900), to: rand(1200, 1800), dur: 0.06, level: 0.04 * L, dest: out });
        break;
      }
      case "tick":
        for (let i = 0; i < 4; i++) this.burst(t + i * 0.5, { dur: 0.012, type: "bandpass", freq: i % 2 ? 2600 : 3200, q: 5, level: 0.25 * L, dest: out });
        break;
      case "gust": {
        const s = this.src("brown");
        const f = this.filter("bandpass", 600, 0.7);
        const g = this.gain(0);
        g.gain.setValueAtTime(0, t);
        g.gain.linearRampToValueAtTime(0.7 * L, t + 0.7);
        g.gain.linearRampToValueAtTime(0, t + 1.8);
        f.frequency.linearRampToValueAtTime(1100, t + 0.8);
        s.connect(f).connect(g).connect(out);
        s.stop(t + 2);
        break;
      }
      default:
        break;
    }
  }

  stop() {
    for (const layer of this.layers.values()) { layer.stop(); layer.out.disconnect(); }
    this.layers.clear();
  }
}
