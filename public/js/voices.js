// The Narrator's three engines:
//  · device — the browser's own neural voices (Web Speech API): instant, free, no server load (superb in Edge)
//  · studio — Kokoro-82M on the server (open weights)
//  · cloud  — Gemini TTS on the server (expressive)
// "Auto" picks by measured speed so the story never stutters; every engine falls back to the device voices.
import { postForBlob } from "./api.js";

// Well-known neural voices: first name -> [gender, accent, age]
const KNOWN = {
  Ava: ["female", "american", "adult"], Andrew: ["male", "american", "adult"], Emma: ["female", "american", "adult"],
  Brian: ["male", "american", "adult"], Jenny: ["female", "american", "adult"], Guy: ["male", "american", "adult"],
  Aria: ["female", "american", "adult"], Ana: ["female", "american", "child"], Christopher: ["male", "american", "adult"],
  Eric: ["male", "american", "adult"], Michelle: ["female", "american", "adult"], Roger: ["male", "american", "elder"],
  Steffan: ["male", "american", "adult"], Sonia: ["female", "british", "adult"], Ryan: ["male", "british", "adult"],
  Libby: ["female", "british", "adult"], Maisie: ["female", "british", "child"], Thomas: ["male", "british", "elder"],
  Natasha: ["female", "other", "adult"], William: ["male", "other", "adult"], Clara: ["female", "other", "adult"],
  Liam: ["male", "other", "adult"], Emily: ["female", "other", "adult"], Connor: ["male", "other", "adult"],
  Molly: ["female", "other", "adult"], Mitchell: ["male", "other", "adult"], Neerja: ["female", "other", "adult"],
  Prabhat: ["male", "other", "adult"], Leah: ["female", "other", "adult"], Luke: ["male", "other", "adult"],
  Samantha: ["female", "american", "adult"], Alex: ["male", "american", "adult"], Daniel: ["male", "british", "adult"],
  Karen: ["female", "other", "adult"], Moira: ["female", "other", "adult"], Fiona: ["female", "british", "adult"],
  Serena: ["female", "british", "adult"], Arthur: ["male", "british", "adult"], Martha: ["female", "british", "elder"],
  Zira: ["female", "american", "adult"], David: ["male", "american", "adult"], Hazel: ["female", "british", "adult"],
  George: ["male", "british", "adult"], Susan: ["female", "british", "adult"], Mark: ["male", "american", "adult"],
};
const QUALITY = /natural|neural|online|premium|enhanced|siri/i;
const RATE = { neutral: 1, warm: 0.97, calm: 0.94, excited: 1.07, playful: 1.04, whisper: 0.9, tense: 1.03, scared: 1.05, sad: 0.9, awe: 0.93 };
const PITCH = { neutral: 1, warm: 1, calm: 0.98, excited: 1.06, playful: 1.05, whisper: 0.96, tense: 1.02, scared: 1.06, sad: 0.95, awe: 1.02 };

export function loadDeviceVoices(timeout = 2500) {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve([]);
    const done = () => resolve(speechSynthesis.getVoices().filter((v) => /^en/i.test(v.lang)));
    if (speechSynthesis.getVoices().length) return done();
    speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, timeout);
  });
}

function profileOf(voice) {
  const name = (voice.name.match(/Microsoft\s+([A-Za-z]+)/) || voice.name.match(/^([A-Z][a-z]+)/) || [])[1] || "";
  const known = KNOWN[name];
  let [gender, accent, age] = known || ["unknown", "other", "adult"];
  if (!known) {
    if (/female|woman/i.test(voice.name)) gender = "female";
    else if (/male|man/i.test(voice.name)) gender = "male";
    accent = /GB|UK/i.test(voice.lang + voice.name) ? "british" : /US/i.test(voice.lang) ? "american" : "other";
  }
  return { name: name || voice.name.split(" ")[0], gender, accent, age, quality: QUALITY.test(voice.name) ? 2 : voice.localService ? 0 : 1,
    multilingual: /multilingual/i.test(voice.name) };
}

/** Match every speaker to a distinct device voice by gender, age, accent and quality. */
export function castDevice(cast, voices) {
  const pool = voices.map((voice) => ({ voice, p: profileOf(voice) }));
  const used = new Set();
  const map = {};
  const order = ["narrator", "host", ...Object.keys(cast).filter((k) => k !== "narrator" && k !== "host")];
  for (const id of order) {
    const want = cast[id];
    if (!want) continue;
    const wantAge = want.age === "child" || want.age === "teen" ? "child" : want.age;
    const score = ({ p }) => (p.gender === want.gender || want.gender === "neutral" ? 3 : 0)
      + (wantAge === "child" ? (p.age === "child" ? 5 : 0) : (p.age === "child" ? -6 : 0))
      + (p.age === "elder" && wantAge === "elder" ? 2 : 0)
      + (p.accent === want.accent ? 2 : p.accent === "other" ? 0.5 : 0)
      + p.quality * 2 - (p.multilingual ? 0.3 : 0);
    const candidates = pool.filter((x) => !used.has(x.voice.name)).sort((a, b) => score(b) - score(a));
    const pick = candidates[0] || pool.sort((a, b) => score(b) - score(a))[0];
    if (!pick) continue;
    used.add(pick.voice.name);
    // child characters on an adult voice get a lift; boys on a girl's voice a little lower
    let pitch = want.pitch || 1;
    if (wantAge === "child" && pick.p.age !== "child") pitch = Math.max(pitch, 1.18);
    if (wantAge === "child" && pick.p.age === "child" && want.gender === "male") pitch = 0.94;
    map[id] = { voice: pick.voice, pitch, rate: want.speed || 1, label: pick.p.name };
  }
  return map;
}

export class DeviceEngine {
  constructor(audience) {
    this.name = "device";
    this.base = audience === "kids" ? 0.93 : 0.99;
    this.map = {};
  }

  assign(cast, voices) { this.map = castDevice(cast, voices); }
  label(id) { return this.map[id]?.label || "device voice"; }
  prefetch() {}

  speak(item, hooks = {}) {
    return new Promise((resolve) => {
      const v = this.map[item.speaker] || this.map.narrator || {};
      const u = new SpeechSynthesisUtterance(item.text);
      if (v.voice) { u.voice = v.voice; u.lang = v.voice.lang; }
      u.rate = Math.min(1.4, this.base * (v.rate || 1) * (RATE[item.delivery] || 1));
      u.pitch = Math.min(1.5, (v.pitch || 1) * (PITCH[item.delivery] || 1));
      u.volume = item.delivery === "whisper" ? 0.82 : 1;
      let finished = false;
      const finish = () => { if (!finished) { finished = true; clearTimeout(guard); resolve(); } };
      // Some browsers occasionally never fire onend: a generous guard keeps the story moving.
      const guard = setTimeout(() => { speechSynthesis.cancel(); finish(); }, 4000 + item.text.length * 140);
      u.onstart = () => hooks.onStart?.(item.text.split(/\s+/).length / (2.6 * u.rate));
      u.onboundary = (e) => hooks.onBoundary?.(e.charIndex);
      u.onend = finish;
      u.onerror = finish;
      speechSynthesis.speak(u);
    });
  }

  stop() { speechSynthesis.cancel(); }
}

/** Test double for the automated UI test (open the page with ?voices=sim): "speaks" in real time, silently,
 *  with word boundaries — headless browsers cannot speak, which would make every timing meaningless. */
export class SimEngine extends DeviceEngine {
  constructor(audience) { super(audience); this.name = "simulated"; }

  speak(item, hooks = {}) {
    return new Promise((resolve) => {
      const v = this.map[item.speaker] || this.map.narrator || {};
      const rate = Math.min(1.4, this.base * (v.rate || 1) * (RATE[item.delivery] || 1));
      const words = [...item.text.matchAll(/\S+/g)];
      const seconds = words.length / (2.5 * rate);
      hooks.onStart?.(seconds);
      const timers = words.map((m, i) => setTimeout(() => hooks.onBoundary?.(m.index), (i / words.length) * seconds * 1000));
      const done = setTimeout(() => { this.cancel = null; resolve(); }, seconds * 1000);
      this.cancel = () => { timers.forEach(clearTimeout); clearTimeout(done); this.cancel = null; resolve(); };
    });
  }

  stop() { this.cancel?.(); }
}

export class ServerEngine {
  // How long a line may wait for its audio before the browser's own voice speaks it instead: never a long pause.
  // A line whose audio is already being made gets a little longer — a short pause beats a sudden change of voice.
  static WAIT_MS = 2500;
  static GRACE_MS = 3000;

  constructor(name, mixer, fallback) {
    this.name = name;
    this.mixer = mixer;
    this.fallback = fallback;
    this.cache = new Map();
    this.active = 0;
    this.waiting = [];
    this.inflight = new Set();
    this.failures = 0;
    this.controller = new AbortController();
  }

  assign(cast) { this.cast = cast; }
  label(id) { const v = this.cast?.[id] || {}; return this.name === "cloud" ? v.gemini : this.name === "neural" ? (v.edge || "").replace(/^en-\w\w-|Neural$/g, "") : v.kokoro; }
  key(item) { return `${item.speaker}|${item.delivery}|${item.text}`; }

  _slot(key) {
    const limit = this.name === "neural" ? 6 : this.name === "cloud" ? 2 : 1;
    if (this.active < limit) { this.active += 1; return Promise.resolve(); }
    return new Promise((resolve) => this.waiting.push({ key, resolve }));
  }
  _release() { this.active -= 1; const next = this.waiting.shift(); if (next) { this.active += 1; next.resolve(); } }
  /** A line needed right now jumps the queue (e.g. after a wish rewrote the rest of the story). */
  _urgent(key) {
    const i = this.waiting.findIndex((w) => w.key === key);
    if (i > 0) this.waiting.unshift(...this.waiting.splice(i, 1));
  }

  /** Audio for one line (cached). Lines are requested in story order, so the next ones are always ready first. */
  get(item) {
    const key = this.key(item);
    if (!this.cache.has(key)) {
      const job = (async () => {
        await this._slot(key);
        this.inflight.add(key);
        try {
          const { blob } = await postForBlob("/api/tts", { text: item.text, voice: this.cast?.[item.speaker] || this.cast?.narrator || {},
            delivery: item.delivery || "neutral", engine: this.name }, this.controller.signal);
          return await this.mixer.decode(await blob.arrayBuffer());
        } finally { this.inflight.delete(key); this._release(); }
      })();
      job.catch(() => this.cache.delete(key)); // a failed line may be tried again later
      this.cache.set(key, job);
    }
    return this.cache.get(key);
  }

  prefetch(items) { for (const item of items) if (item?.text) this.get(item).catch(() => {}); }

  async speak(item, hooks = {}) {
    let buffer;
    try {
      const key = this.key(item);
      const job = this.get(item);
      this._urgent(key);
      const within = (ms) => Promise.race([job, new Promise((r) => setTimeout(() => r(null), ms))]);
      buffer = await within(ServerEngine.WAIT_MS);
      if (!buffer && this.inflight.has(key)) buffer = await within(ServerEngine.GRACE_MS);
    } catch { buffer = null; }
    if (!buffer) { // not ready in time (or failed): the browser's own voice tells this line, the story never stalls
      this.failures += 1;
      return this.fallback.speak(item, hooks);
    }
    await this.mixer.playVoice(buffer, () => hooks.onStart?.(buffer.duration));
  }

  stop() { this.mixer.stopVoice(); this.fallback?.stop(); }
  /** The story ended or the listener left: cancel every request still in flight. */
  close() { this.controller.abort(); this.stop(); }
}

/** Choose the voice engine: the user's preference, or (auto) the fastest good one here. */
export function chooseEngine(pref, health, deviceList) {
  const natural = deviceList.filter((v) => QUALITY.test(v.name));
  const voices = health?.voices || {};
  if (pref === "device") return { engine: "device", why: "you chose your device's voices" };
  if (pref === "neural" && voices.neural?.available) return { engine: "neural", why: "you chose the neural voices" };
  if (pref === "studio" && voices.studio?.available) return { engine: "studio", why: "you chose the studio (Kokoro) voices" };
  if (pref === "cloud" && voices.cloud?.available) return { engine: "cloud", why: "you chose Gemini's expressive voices" };
  if (natural.length >= 4) return { engine: "device", why: `${natural.length} neural voices are built into this browser — instant and free` };
  if (voices.neural?.available) return { engine: "neural", why: "Microsoft neural voices from the server, prepared ahead for the whole story" };
  return { engine: "device", why: "your browser's built-in voices" };
}
