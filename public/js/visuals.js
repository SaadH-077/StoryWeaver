// The Illustrator's side of the stage: requests pictures (with priorities and character references), shows them
// with slow cinematic camera moves and cross-fades, paints a mood backdrop while a picture is on its way, and adds
// weather particles that match the soundscape.
import { blobToDataURL, postForBlob } from "./api.js";
import { paintScene } from "./painter.js";

const MOODS = {
  wonder: ["#2b2560", "#4a2a6b"], adventure: ["#4a2a1a", "#1d3b4f"], mystery: ["#1a2a3a", "#2c1f3d"],
  tension: ["#3d1d22", "#1d1d2e"], calm: ["#1b3a3a", "#2a3550"], joy: ["#4c3a1a", "#1f4a45"],
  melancholy: ["#1d2533", "#2f2a3f"], triumph: ["#4a361a", "#3a1f2a"],
};
const MOVES = ["kb-in", "kb-out", "kb-left", "kb-right"];

export class Visuals {
  constructor({ shotA, shotB, painted, particles }) {
    this.slots = [shotA, shotB];
    this.flip = 0;
    this.painted = painted;
    this.particles = new Particles(particles);
    this.queue = [];
    this.active = 0;
    this.cache = new Map();
    this.portraits = new Map(); // character id -> { url, data }
    this.stats = { requested: 0, done: 0, failed: 0, providers: {}, ms: [] };
    this.scene = { ambience: ["wind"], mood: "wonder", seed: "story" }; // for pictures painted in the browser
    this.onStat = () => {};
    this.controller = new AbortController();
  }

  configure(bible) {
    this.bible = bible;
    this.style = bible.art_style;
    this.looks = Object.fromEntries(bible.characters.map((c) => [c.id, `${c.name}: ${c.look}`]));
    this.names = bible.characters.map((c) => [c.id, c.name.split(" ")[0].toLowerCase()]);
  }

  /** Cancel every pending picture (the listener left this story). */
  close() {
    this.controller.abort();
    for (const job of this.queue.splice(0)) job.resolve(null);
  }

  setMood(mood) {
    this.scene.mood = mood;
    const [a, b] = MOODS[mood] || MOODS.wonder;
    this.painted.style.setProperty("--m1", a);
    this.painted.style.setProperty("--m2", b);
  }

  setAmbience(list) { this.scene.ambience = list || []; this.particles.set(list || []); }

  /** A paper-cut scene painted right here — instant, and the fallback when no image model can deliver. */
  paint(scene = {}) { return paintScene({ ...this.scene, ...scene }); }

  show(url) {
    if (!url) return;
    const next = this.slots[this.flip];
    const prev = this.slots[1 - this.flip];
    if (prev.dataset.url === url) return;
    this.flip = 1 - this.flip;
    next.onload = () => {
      next.className = `shot on ${MOVES[Math.floor(Math.random() * MOVES.length)]}`;
      prev.classList.remove("on");
    };
    next.dataset.url = url;
    next.src = url;
  }

  clear() {
    for (const img of this.slots) { img.className = "shot"; img.removeAttribute("src"); delete img.dataset.url; }
    this.particles.set([]);
  }

  /** Characters visible in a shot: the writer's list, or anyone whose name appears in the description. */
  charactersIn(shot) {
    if (shot.characters?.length) return shot.characters;
    const text = (shot.description || "").toLowerCase();
    return this.names.filter(([, name]) => text.includes(name)).map(([id]) => id);
  }

  /** deadline: seconds until the picture is on screen — the server picks the best model that is fast enough. */
  sceneSpec(description, characterIds = [], deadline = 0, scene = null) {
    const ids = characterIds.filter((id) => this.looks[id]).slice(0, 3);
    const references = ids.map((id) => this.portraits.get(id)?.data).filter(Boolean).slice(0, 2);
    return { description, style: this.style, looks: ids.map((id) => this.looks[id]), kind: "scene", references,
      width: 768, height: 512, deadline_s: Math.max(0, Math.round(deadline)),
      scene: { ...this.scene, ...(scene || {}), seed: `${this.scene.seed}|${description}` } };
  }

  /** Queue a picture; lower priority numbers are painted first. Resolves to an object URL (or null). */
  request(key, spec, priority = 5) {
    if (this.cache.has(key)) return this.cache.get(key);
    const promise = new Promise((resolve) => {
      this.queue.push({ spec, priority, resolve, key });
      this.queue.sort((a, b) => a.priority - b.priority);
      this._pump();
    });
    this.cache.set(key, promise);
    return promise;
  }

  async portrait(character) {
    const spec = { description: `${character.name}, ${character.role}. ${character.look}`, style: this.style,
      looks: [], kind: "portrait", references: [], width: 512, height: 512, deadline_s: 0 };
    const url = await this.request(`portrait:${character.id}`, spec, 1);
    if (url) {
      const blob = await fetch(url).then((r) => r.blob());
      this.portraits.set(character.id, { url, data: await blobToDataURL(blob) });
    }
    return url;
  }

  _pump() {
    while (this.active < 3 && this.queue.length) {
      const job = this.queue.shift();
      this.active += 1;
      this.stats.requested += 1;
      const t0 = performance.now();
      postForBlob("/api/image", job.spec, this.controller.signal)
        .then(({ blob, headers }) => {
          const provider = headers.get("X-Provider") || "?";
          this.stats.done += 1;
          this.stats.providers[provider] = (this.stats.providers[provider] || 0) + 1;
          this.stats.ms.push(performance.now() - t0);
          job.resolve(URL.createObjectURL(blob));
        })
        .catch(() => { // no model could paint it: scenes get a paper-cut picture painted here instead
          this.stats.failed += 1;
          job.resolve(job.spec.kind === "scene" ? this.paint(job.spec.scene) : null);
        })
        .finally(() => { this.active -= 1; this.onStat(this.stats); this._pump(); });
    }
  }
}

class Particles {
  constructor(canvas) {
    this.cv = canvas;
    this.cx = canvas.getContext("2d");
    this.kind = null;
    this.items = [];
    this.running = false;
    addEventListener("resize", () => this.resize());
    this.resize();
  }

  resize() { this.cv.width = this.cv.clientWidth || innerWidth; this.cv.height = this.cv.clientHeight || innerHeight; }

  set(ambience) {
    const kind = ambience.some((a) => a === "rain" || a === "storm") ? "rain" : ambience.includes("fire") ? "embers"
      : ambience.includes("underwater") ? "bubbles" : ambience.includes("magic") ? "sparkles"
      : ambience.some((a) => a === "space" || a === "night") ? "stars" : ambience.includes("forest") ? "motes" : null;
    if (kind === this.kind) return;
    this.kind = kind;
    const count = { rain: 70, embers: 28, bubbles: 22, stars: 60, sparkles: 34, motes: 26 }[kind] || 0;
    this.items = Array.from({ length: count }, () => this.spawn(true));
    if (!this.running && kind) { this.running = true; requestAnimationFrame(() => this.frame()); }
  }

  spawn(anywhere) {
    const w = this.cv.width, h = this.cv.height;
    return { x: Math.random() * w, y: anywhere ? Math.random() * h : (this.kind === "rain" ? -20 : h + 10),
      v: 0.4 + Math.random(), a: Math.random(), p: Math.random() * 6.28 };
  }

  frame() {
    if (!this.kind) { this.running = false; this.cx.clearRect(0, 0, this.cv.width, this.cv.height); return; }
    this.tick = (this.tick || 0) + 1;
    if (this.tick % 2) { requestAnimationFrame(() => this.frame()); return; } // ~30 fps is plenty
    const { cx } = this, w = this.cv.width, h = this.cv.height;
    cx.clearRect(0, 0, w, h);
    for (const p of this.items) {
      switch (this.kind) {
        case "rain":
          p.y += 14 * p.v; p.x -= 2 * p.v;
          cx.strokeStyle = `rgba(190,215,255,${0.1 + 0.18 * p.a})`; cx.lineWidth = 1;
          cx.beginPath(); cx.moveTo(p.x, p.y); cx.lineTo(p.x + 3, p.y - 16 * p.v); cx.stroke();
          if (p.y > h + 20) Object.assign(p, this.spawn(false));
          break;
        case "stars": case "sparkles":
          p.p += 0.03 * p.v;
          cx.fillStyle = this.kind === "sparkles" ? `rgba(255,228,170,${0.6 * (0.5 + 0.5 * Math.sin(p.p)) * p.a})`
            : `rgba(255,245,220,${0.15 + 0.35 * (0.5 + 0.5 * Math.sin(p.p)) * p.a})`;
          cx.beginPath(); cx.arc(p.x, p.y * (this.kind === "stars" ? 0.7 : 1), this.kind === "sparkles" ? 1.8 : 1.2, 0, 6.28); cx.fill();
          if (this.kind === "sparkles") { p.y -= 0.25 * p.v; if (p.y < -10) Object.assign(p, this.spawn(false)); }
          break;
        case "embers": case "motes":
          p.y -= (this.kind === "embers" ? 1.2 : 0.35) * p.v; p.x += Math.sin(p.p += 0.03) * 0.6;
          cx.fillStyle = this.kind === "embers" ? `rgba(255,${140 + 60 * p.a},60,${0.55 * p.a})` : `rgba(255,250,210,${0.35 * p.a})`;
          cx.beginPath(); cx.arc(p.x, p.y, 1.4 + p.a * 1.4, 0, 6.28); cx.fill();
          if (p.y < -10) Object.assign(p, this.spawn(false));
          break;
        case "bubbles":
          p.y -= 0.9 * p.v; p.x += Math.sin(p.p += 0.04) * 0.5;
          cx.strokeStyle = `rgba(200,240,255,${0.25 * p.a + 0.1})`;
          cx.beginPath(); cx.arc(p.x, p.y, 2 + 4 * p.a, 0, 6.28); cx.stroke();
          if (p.y < -10) Object.assign(p, this.spawn(false));
          break;
        default: break;
      }
    }
    requestAnimationFrame(() => this.frame());
  }
}
