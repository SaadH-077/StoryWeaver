// Generative, adaptive score. The Showrunner picks a mood per chapter and a tension value along a
// Freytag arc; the score turns that into harmony, tempo and density — swelling toward the climax and
// settling in the resolution. Synthesised live (pads, bass, arpeggio, bells) — no music files.

const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
const rand = (a, b) => a + Math.random() * (b - a);

const MAJ = { I: [0, 4, 7, 11], ii: [2, 5, 9, 12], IV: [5, 9, 12, 16], V: [7, 11, 14, 17], vi: [9, 12, 16, 19], II: [2, 6, 9, 13] };
const MIN = { i: [0, 3, 7, 10], iv: [5, 8, 12, 15], v: [7, 10, 14, 17], V: [7, 11, 14, 17], VI: [8, 12, 15, 19], VII: [10, 14, 17, 20], III: [3, 7, 10, 14] };

const MOODS = {
  wonder:     { root: 53, prog: [MAJ.I, MAJ.II, MAJ.vi, MAJ.IV], bpm: 64, cutoff: 1500, wave: "triangle", arp: 0.45, bells: 0.35 },
  adventure:  { root: 50, prog: [MIN.i, MIN.VII, MIN.VI, MIN.VII], bpm: 92, cutoff: 2100, wave: "sawtooth", arp: 0.8, bells: 0.05, pulse: true },
  mystery:    { root: 52, prog: [MIN.i, MIN.VI, MIN.iv, MIN.v], bpm: 58, cutoff: 950, wave: "triangle", arp: 0.3, bells: 0.2 },
  tension:    { root: 49, prog: [MIN.i, MIN.i, MIN.VI, MIN.V], bpm: 80, cutoff: 1150, wave: "sawtooth", arp: 0.55, bells: 0, pulse: true },
  calm:       { root: 55, prog: [MAJ.I, MAJ.IV, MAJ.I, MAJ.V], bpm: 54, cutoff: 1000, wave: "sine", arp: 0.25, bells: 0.15 },
  joy:        { root: 60, prog: [MAJ.I, MAJ.V, MAJ.vi, MAJ.IV], bpm: 100, cutoff: 2600, wave: "triangle", arp: 0.85, bells: 0.3 },
  melancholy: { root: 57, prog: [MIN.i, MIN.VI, MIN.III, MIN.VII], bpm: 56, cutoff: 900, wave: "triangle", arp: 0.25, bells: 0.1 },
  triumph:    { root: 50, prog: [MAJ.I, MAJ.V, MAJ.vi, MAJ.IV], bpm: 88, cutoff: 2400, wave: "sawtooth", arp: 0.75, bells: 0.25, pulse: true },
};

class Layer {
  constructor(engine, mood, intensity) {
    this.e = engine;
    this.c = engine.ctx;
    this.m = MOODS[mood] || MOODS.wonder;
    this.intensity = intensity;
    this.out = this.c.createGain();
    this.out.gain.value = 0;
    this.out.connect(engine.musicBus);
    this.padFilter = this.c.createBiquadFilter();
    this.padFilter.type = "lowpass";
    this.padFilter.Q.value = 0.6;
    this.padFilter.connect(this.out);
    this.beat = 60 / this.m.bpm;
    this.step = 0;
    this.nextTime = this.c.currentTime + 0.1;
    this.alive = true;
    this.applyIntensity(intensity, 0.1);
    this.timer = setInterval(() => this.schedule(), 80);
  }

  applyIntensity(value, ramp = 3) {
    this.intensity = Math.max(0, Math.min(1, value));
    const t = this.c.currentTime;
    this.padFilter.frequency.setTargetAtTime(this.m.cutoff * (0.55 + 0.9 * this.intensity), t, ramp);
  }

  fadeIn(seconds = 4) { this.out.gain.setTargetAtTime(0.75 + 0.35 * this.intensity, this.c.currentTime, seconds / 3); }

  fadeOut(seconds = 4) {
    this.out.gain.setTargetAtTime(0, this.c.currentTime, seconds / 3);
    setTimeout(() => this.stop(), seconds * 1500);
  }

  stop() {
    if (!this.alive) return;
    this.alive = false;
    clearInterval(this.timer);
    setTimeout(() => this.out.disconnect(), 4000);
  }

  schedule() {
    if (!this.alive || this.c.state !== "running") return;
    while (this.nextTime < this.c.currentTime + 0.25) {
      this.playStep(this.step, this.nextTime);
      this.step += 1;
      this.nextTime += this.beat / 2; // eighth notes
    }
  }

  chordAt(step) {
    const bar = Math.floor(step / 8);
    return this.m.prog[Math.floor(bar / 2) % this.m.prog.length]; // two bars per chord
  }

  playStep(step, t) {
    const chord = this.chordAt(step);
    const root = this.m.root;
    if (step % 16 === 0) this.pad(chord, t, this.beat * 8.4);
    if (step % 16 === 0) this.bass(root + chord[0] - 12, t, this.beat * 8);
    if (this.m.pulse && step % 2 === 0 && this.intensity > 0.45) this.pluck(root + chord[0] - 12, t, 0.07 * this.intensity, "triangle", 0.18);
    const arpChance = this.m.arp * (0.15 + 0.85 * this.intensity);
    if (Math.random() < arpChance) {
      const note = root + 12 + chord[step % chord.length];
      this.pluck(note, t, 0.045 + 0.04 * this.intensity, "triangle", this.beat * 0.9);
    }
    if (step % 4 === 0 && Math.random() < this.m.bells * 0.5) {
      this.bell(root + 24 + chord[Math.floor(rand(0, chord.length))], t + rand(0, 0.1));
    }
  }

  pad(chord, t, dur) {
    for (const interval of chord) {
      for (const detune of [-7, 6]) {
        const o = this.c.createOscillator();
        o.type = this.m.wave;
        o.frequency.value = midi(this.m.root + interval);
        o.detune.value = detune;
        const g = this.c.createGain();
        const level = (this.m.wave === "sawtooth" ? 0.012 : 0.022) * (0.7 + 0.5 * this.intensity);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.linearRampToValueAtTime(level, t + 1.8);
        g.gain.setValueAtTime(level, t + dur - 1.4);
        g.gain.linearRampToValueAtTime(0.0001, t + dur + 1.2);
        o.connect(g).connect(this.padFilter);
        o.start(t);
        o.stop(t + dur + 1.3);
      }
    }
  }

  bass(note, t, dur) {
    const o = this.c.createOscillator();
    o.type = "sine";
    o.frequency.value = midi(note);
    const g = this.c.createGain();
    const level = 0.05 + 0.03 * this.intensity;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(level, t + 0.6);
    g.gain.setValueAtTime(level, t + dur - 0.8);
    g.gain.linearRampToValueAtTime(0.0001, t + dur + 0.4);
    o.connect(g).connect(this.out);
    o.start(t);
    o.stop(t + dur + 0.5);
  }

  pluck(note, t, level, type, dur) {
    const o = this.c.createOscillator();
    o.type = type;
    o.frequency.value = midi(note);
    const f = this.c.createBiquadFilter();
    f.type = "lowpass";
    f.frequency.value = 900 + 1800 * this.intensity;
    const g = this.c.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(level, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(f).connect(g).connect(this.out);
    g.connect(this.e.reverb);
    o.start(t);
    o.stop(t + dur + 0.05);
  }

  bell(note, t) {
    [1, 2.76].forEach((mult, i) => {
      const o = this.c.createOscillator();
      o.frequency.value = midi(note) * mult;
      const g = this.c.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.02 / (i + 1), t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 2.4);
      o.connect(g).connect(this.out);
      g.connect(this.e.reverb);
      o.start(t);
      o.stop(t + 2.5);
    });
  }
}

const MAJOR = [0, 2, 4, 5, 7, 9, 11, 12];
const MINOR = [0, 2, 3, 5, 7, 8, 10, 12];
const NOTE_NAMES = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
const MINOR_MOODS = new Set(["mystery", "tension", "melancholy", "adventure"]);

/** A story's leitmotif: six notes derived from its title, in the key of its opening mood. */
export function themeFor(seed, mood = "wonder") {
  const m = MOODS[mood] || MOODS.wonder;
  let h = 2166136261;
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  const scale = MINOR_MOODS.has(mood) ? MINOR : MAJOR;
  const steps = [];
  for (let i = 0; i < 5; i++) steps.push(scale[(h >>> (i * 5)) % 7]);
  steps.push(0); // always come home to the root
  return { notes: steps.map((s) => m.root + 12 + s), key: `${NOTE_NAMES[m.root % 12]} ${MINOR_MOODS.has(mood) ? "minor" : "major"}`,
    tempo: m.bpm };
}

export class Score {
  constructor(engine) { this.e = engine; this.layer = null; this.mood = null; }

  /** Play the leitmotif as a soft music box (title card and ending). */
  theme(seed, mood) {
    const { notes } = themeFor(seed, mood || this.mood || "wonder");
    const c = this.e.ctx;
    const start = c.currentTime + 0.1;
    notes.forEach((note, i) => {
      const t = start + i * 0.34 + (i === notes.length - 1 ? 0.18 : 0);
      [1, 3.01].forEach((mult, k) => {
        const o = c.createOscillator();
        o.type = k ? "triangle" : "sine";
        o.frequency.value = midi(note) * mult;
        const g = c.createGain();
        const peak = (k ? 0.012 : 0.05) * (i === notes.length - 1 ? 1.2 : 1);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(peak, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + (i === notes.length - 1 ? 2.6 : 1.2));
        o.connect(g).connect(this.e.musicBus);
        g.connect(this.e.reverb);
        o.start(t);
        o.stop(t + 2.8);
      });
    });
  }

  /** Move to a mood/intensity; a mood change crossfades to a new layer, otherwise intensity glides. */
  set(mood, intensity = 0.5) {
    if (!MOODS[mood]) mood = "wonder";
    if (this.layer && mood === this.mood) {
      this.layer.applyIntensity(intensity);
      this.layer.fadeIn(3);
      return;
    }
    if (this.layer) this.layer.fadeOut(5);
    this.mood = mood;
    this.layer = new Layer(this.e, mood, intensity);
    this.layer.fadeIn(5);
  }

  stop() { if (this.layer) this.layer.fadeOut(3); this.layer = null; this.mood = null; }
}
