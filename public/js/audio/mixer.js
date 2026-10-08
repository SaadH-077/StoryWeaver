// Web Audio mixer: music, ambience, effects and server-voice buses, with radio-style ducking under speech.
export class Mixer {
  async init() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const c = (this.ctx = new Ctx({ latencyHint: "playback" }));
    this.master = this._gain(0.95, null);
    const comp = c.createDynamicsCompressor();
    comp.threshold.value = -16; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.01; comp.release.value = 0.25;
    this.master.connect(comp).connect(c.destination);
    this.voiceBus = this._gain(1.0, this.master);
    this.musicDuck = this._gain(1.0, this.master);
    this.ambDuck = this._gain(1.0, this.master);
    this.musicBus = this._gain(0.7 * 0.5, this.musicDuck);
    this.ambBus = this._gain(0.8 * 0.55, this.ambDuck);
    this.sfxBus = this._gain(0.75, this.master);
    this.reverb = c.createConvolver();
    this.reverb.buffer = this._impulse(2.8, 2.2);
    this.reverb.connect(this._gain(0.36, this.master));
    this.releaseTimer = null;
    if (c.state === "suspended") await c.resume();
  }

  _gain(value, dest) {
    const g = this.ctx.createGain();
    g.gain.value = value;
    if (dest) g.connect(dest);
    return g;
  }

  _impulse(seconds, decay) {
    const rate = this.ctx.sampleRate, len = Math.floor(rate * seconds);
    const buf = this.ctx.createBuffer(2, len, rate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
    }
    return buf;
  }

  /** Lower music and ambience while someone speaks; bring them back gently afterwards. */
  duck(speaking) {
    const t = this.ctx.currentTime;
    clearTimeout(this.releaseTimer);
    const apply = (level, tau) => {
      for (const node of [this.musicDuck, this.ambDuck]) {
        node.gain.cancelScheduledValues(t);
        node.gain.setTargetAtTime(level, t, tau);
      }
    };
    if (speaking) apply(0.4, 0.15);
    else this.releaseTimer = setTimeout(() => apply(1.0, 0.8), 700);
  }

  async decode(arrayBuffer) { return this.ctx.decodeAudioData(arrayBuffer); }

  /** Play a decoded voice clip; resolves when it ends (or is stopped). */
  playVoice(buffer, onStart) {
    return new Promise((resolve) => {
      const src = this.ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(this.voiceBus);
      this.currentVoice = src;
      src.onended = () => { if (this.currentVoice === src) this.currentVoice = null; resolve(); };
      src.start();
      onStart?.(this.ctx.currentTime);
    });
  }

  stopVoice() {
    if (this.currentVoice) {
      try { this.currentVoice.stop(); } catch { /* already stopped */ }
      this.currentVoice = null;
    }
  }

  setMusic(v) { this.musicBus.gain.setTargetAtTime(v * 0.5, this.ctx.currentTime, 0.1); }
  setAmbience(v) { this.ambBus.gain.setTargetAtTime(v * 0.55, this.ctx.currentTime, 0.1); }
  async suspend() { await this.ctx.suspend(); }
  async resume() { await this.ctx.resume(); }
  async close() { try { await this.ctx.close(); } catch { /* closed */ } }
}
