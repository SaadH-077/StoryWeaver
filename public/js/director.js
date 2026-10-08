// The Director: runs the story in the browser. One request brings the whole story — opening, every part and both
// endings of the choice — so once narration starts it never waits for a model again. A spoken wish rewrites the
// story from the next sentence on, in the background; if that fails, the story simply continues as it was.
import { postJSON, streamNDJSON } from "./api.js";
import { themeFor } from "./audio/score.js";
import * as ui from "./ui.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
// The whole story is written in ~2-4 s, about as long as the greeting takes to say.
export const GREETINGS = {
  kids: "Snuggle in, little listener. Your story is being woven right now!",
  family: "Settle in, everyone. Your story is being woven right now.",
  adults: "Settle in. Your story is being woven right now.",
};
const HOLD = {
  kids: "Almost ready. The story crew is painting the very first page.",
  family: "Almost ready. The crew is adding the final touches.",
  adults: "Almost there. The crew is adding the final touches.",
};
// the host answers a wish at once (pre-voiced), while the Storyteller rewrites what comes next
const ACKS = {
  kids: "Ooh, what a lovely idea! Let's weave it in.",
  family: "What a lovely idea. Let's weave it in.",
  adults: "Good idea. Let's weave it in.",
};
const WORDS_PER_SECOND = 2.5;
const n = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
const words = (text) => (text || "").split(/\s+/).filter(Boolean).length;
const GOODBYES = {
  kids: (t) => `And that is the end of ${t}. Sweet dreams.`,
  family: (t) => `And that was ${t}. Thank you for listening.`,
  adults: (t) => `That was ${t}. Thank you for listening.`,
};

/** The newcomer a plain wish asks for, from its words alone: "Add a friendly firefly to the story" → "Friendly firefly". */
function newcomerIn(wish) {
  const m = (wish || "").match(/\b(?:add|bring(?:\s+in)?|introduce|include|invite|meet|want|wish for|have)\s+(?:a|an|the|some|my|another)\s+([a-z][a-z' -]{1,40})/i);
  if (!m) return null;
  const what = m[1].replace(/\s+(?:to|into|in|on|at|who|that|which|so|and|with|for)\b.*$/i, "").trim();
  const named = what.match(/^(.*?)\s+(?:named|called)\s+([a-z']+)/i); // "a firefly named Flick" → Flick, a firefly
  const name = named ? named[2] : what;
  return name ? { name: name[0].toUpperCase() + name.slice(1), emoji: "✨", description: named ? named[1] : "" } : null;
}

/** A new name in the rewritten lines: "a firefly named Flick", or a capitalised word that is not the start of a
 *  sentence and is not a known character ("It was Flick, the friendly firefly. Flick glowed…" → Flick). */
function newName(text, known) {
  const called = text.match(/\b(?:named|called)\s+([A-Z][a-z]+)/);
  if (called && !known.has(called[1].toLowerCase())) return called[1];
  const counts = new Map();
  for (const m of text.matchAll(/(?<=[a-z,]\s)([A-Z][a-z]{2,})\b/g)) {
    if (!known.has(m[1].toLowerCase())) counts.set(m[1], (counts.get(m[1]) || 0) + 1);
  }
  return [...counts.entries()].sort((x, y) => y[1] - x[1])[0]?.[0] || null;
}

function sentences(text, maxPerLine = 2) {
  const parts = (text.match(/[^.!?…]+[.!?…]+["”’']?|[^.!?…]+$/g) || [text]).map((s) => s.trim()).filter(Boolean);
  const lines = [];
  for (let i = 0; i < parts.length; i += maxPerLine) lines.push(parts.slice(i, i + maxPerLine).join(" "));
  return lines;
}

export class Director {
  constructor({ request, length, engine, engineInfo, mixer, scape, score, visuals, onExit }) {
    Object.assign(this, { request, length, engine, engineInfo, mixer, scape, score, visuals, onExit });
    this.queue = [];
    this.prepared = new Map();
    this.scripts = [];
    this.summaries = [];
    this.facts = [];
    this.decisions = [];
    this.steers = [];
    this.toldLines = []; // every story sentence the listener has heard (what a wish must continue from)
    this.chapterChecks = [];
    this.metrics = { llm: 0, tokens: 0, fallbacks: 0, gaps: [], readyAhead: 0, chapters: 0, sfx: 0 };
    this.did = {};
    this.live = new Set();
    this.controller = new AbortController();
    this.current = -1;
    this.segment = 0;
    this.kick = null;
  }

  // ===================================================================================== lifecycle
  async start() {
    this.t0 = performance.now();
    ui.showWeaving(this.request.prompt);
    if (this.length) { // the shape is known before the plan: show the outline of the story at once
      ui.renderTimeline(Array.from({ length: this.length.chapters }, (_, i) =>
        ({ title: `Chapter ${i + 1}`, choice: this.length.choice_after?.includes(i + 1) })));
    }
    this.note("narrator", `<b>${this.engineInfo.engine}</b> voices — ${this.engineInfo.why}.`);
    this.loop();
    const greeting = { kind: "host", speaker: "host", text: GREETINGS[this.request.audience], delivery: "warm" };
    this.engine.prefetch([greeting, { kind: "aside", speaker: "host", delivery: "warm", text: ACKS[this.request.audience] }]);
    this.enqueue(greeting);
    setTimeout(() => { // a busy moment on the free tiers: the host fills the pause instead of silence
      if (!this.openingHeard && !this.stopped) this.enqueue({ kind: "host", speaker: "host", delivery: "warm", text: HOLD[this.request.audience] });
    }, 6500);
    let plan;
    try {
      plan = await streamNDJSON("/api/plan", this.request, (e) => this.onEvent(e, "plan"), this.controller.signal);
    } catch (err) {
      if (this.stopped) return;
      ui.hideWeaving();
      ui.toast(err.message, "warn", 8000);
      return this.onExit();
    }
    if (this.stopped) return;
    if (plan.refused) return this.refused(plan);
    if (!this.openingHeard) this.onOpening({ opening: plan.bible, voices: plan.cast }); // safety net
    this.onPlan(plan);
  }

  stop() {
    this.stopped = true;
    this.controller.abort(); // the story stream and any rewrite in flight
    if (this.engine.close) this.engine.close(); else this.engine.stop(); // pending voice requests
    this.visuals.close(); // pending pictures: nothing from this story may hold up the next one
    this.scape.stop();
    this.score.stop();
    this.wake();
  }

  async pause() { this.paused = true; this.engine.stop(); await this.mixer.suspend(); }
  async resume() { this.paused = false; await this.mixer.resume(); this.wake(); }

  enqueue(...items) { this.queue.push(...items); this.wake(); }
  wake() { if (this.kick) { const k = this.kick; this.kick = null; k(); } }

  async loop() {
    while (!this.stopped) {
      if (this.paused || !this.queue.length) { await new Promise((r) => { this.kick = r; }); continue; }
      const item = this.queue.shift();
      try { await this.play(item); } catch (err) { console.error("play failed", item, err); }
    }
  }

  // ===================================================================================== events → crew panel
  note(id, html) { this.did[id] = { ...(this.did[id] || {}), text: html }; this.refreshCrew(); }
  model(id, model) { this.did[id] = { ...(this.did[id] || {}), model }; }
  refreshCrew() { if (!document.getElementById("drawer").hidden) ui.renderCrew(this.did, this.live); }

  onEvent(e, phase, branch = "") {
    const t = performance.now() - this.t0;
    switch (e.type) {
      case "agent": {
        if (e.state === "start") this.live.add(e.agent); else if (e.state !== "queued") this.live.delete(e.agent);
        if (phase === "plan") ui.crewChip(e.agent, e.state, e.detail);
        ui.logEvent(e.state === "waiting" ? "warn" : "agent", e.agent, `${e.state === "start" ? "▸" : e.state === "done" ? "✓" : "…"} ${e.detail || ""}`, branch, t);
        if (e.state === "waiting") ui.toast(`The ${e.agent} is catching its breath (free-tier limit)…`, "", 3500);
        break;
      }
      case "llm":
        this.metrics.llm += 1;
        this.metrics.tokens += (e.input_tokens || 0) + (e.output_tokens || 0);
        if (e.fallbacks?.length) this.metrics.fallbacks += 1;
        this.model(e.role, e.model.replace(/^openai\//, "").replace(/^qwen\//, ""));
        ui.logEvent("llm", e.role, `model call · ${e.ms} ms`, `${e.provider}/${e.model}${e.input_tokens ? ` · ${e.input_tokens}→${e.output_tokens} tokens` : ""}${e.fallbacks?.length ? ` · fallback after ${e.fallbacks.join("; ")}` : ""}`, t);
        break;
      case "tool":
        if (e.state !== "start") ui.logEvent("tool", `${e.agent} · ${e.tool}`, e.detail || "", e.url || "", t);
        break;
      case "safety": {
        this.screening = e;
        const layers = e.layers.map((l) => `${l.layer}: <b>${l.verdict}</b>`).join(" · ");
        this.note("guardian", `Decision: <b>${e.decision}</b>. ${layers}.${e.decision === "soften" ? ` Rewritten as “${ui.esc(e.safe_request)}”.` : ""}`);
        ui.crewChip("guardian", "done", e.decision === "allow" ? "Safe for this audience ✓" : e.decision === "soften" ? "Softened for this audience" : "Not a story we can tell");
        ui.logEvent(e.decision === "allow" ? "safety" : "warn", "guardian", e.decision, e.reason, t);
        if (e.decision === "soften") ui.toast(`Adjusted for your listeners: “${e.safe_request}”`, "good", 6500);
        ui.renderSafety(this.screening, this.chapterChecks);
        break;
      }
      case "opening":
        this.onOpening(e);
        break;
      case "lore":
        this.note("lore", e.facts.length ? `Looked up ${e.sources.map((s) => s.url ? `<a href="${s.url}" target="_blank" rel="noopener">${ui.esc(s.title)}</a>` : ui.esc(s.title)).join(", ")}: ${e.facts.map(ui.esc).join(" · ")}`
          : "Pure imagination — nothing real to look up.");
        ui.crewChip("lore", "done", e.facts.length ? `Found ${e.facts.length} true facts` : "Nothing to look up");
        break;
      case "review":
        this.chapterChecks = this.chapterChecks.filter((c) => !(c.chapter === e.chapter && c.branch === branch));
        this.chapterChecks.push({ chapter: e.chapter, branch, approved: e.approved, grade: e.grade, issues: e.issues });
        ui.renderSafety(this.screening, this.chapterChecks);
        break;
      default: break;
    }
  }

  refused(plan) {
    ui.hideWeaving();
    document.body.dataset.view = "stage";
    const s = plan.safety;
    this.enqueue({ kind: "host", speaker: "host", delivery: "warm",
      text: `I'm sorry, that isn't a story I can tell. ${s.alternatives?.length ? `How about ${s.alternatives[0]} instead?` : ""}` });
    ui.showRefusal(s.reason, s.alternatives || [], (idea) => this.onExit(idea));
  }

  // ===================================================================================== opening + plan
  /** The approved story arrives ~2-4 s after the request: the title card and the opening start at once. */
  onOpening({ opening: o, voices }) {
    if (this.openingHeard || this.stopped) return;
    this.openingHeard = true;
    this.openingAt = performance.now() - this.t0;
    this.engine.assign(voices, this.deviceVoices);
    this.engine.fallback?.assign(voices, this.deviceVoices);
    this.visuals.configure({ art_style: o.art_style, characters: [{ id: "hero", name: o.hero_name, look: o.hero_look }] });
    this.visuals.scene.seed = o.title;
    this.visuals.setMood(o.opening_music);
    this.visuals.setAmbience(o.opening_ambience);
    this.visuals.show(this.visuals.paint()); // an illustrated sky at once; the first picture fades in over it
    this.scape.set(o.opening_ambience, 0.3);
    this.score.set(o.opening_music, 0.25);
    this.title = o.title;
    ui.crewChip("storyteller", "done", `“${o.title}”`);
    ui.setTitles(o.title, "Once upon a time…");
    const theme = themeFor(o.title, o.opening_music);
    this.note("storyteller", `“<b>${ui.esc(o.title)}</b>” — ${ui.esc(o.logline)}<br>Hero: <b>${ui.esc(o.hero_name)}</b>, ${ui.esc(o.hero_look)}. Art style: ${ui.esc(o.art_style)}. The whole story was written and checked after <b>${(this.openingAt / 1000).toFixed(1)} s</b>.`);
    this.note("composer", `A theme for this story in <b>${theme.key}</b> (${theme.notes.length} notes, ${theme.tempo} bpm); harmony and intensity follow the tension of each chapter.`);
    this.note("sound", `Opening soundscape: <b>${o.opening_ambience.join(" + ")}</b>.`);

    // the establishing picture (one of the story's fixed budget of pictures: one per minute)
    this.opening = this.visuals.request("opening", this.visuals.sceneSpec(o.opening_shot, ["hero"], 0), 0);
    this.opening.then((url) => { if (url && this.segment === 0) this.visuals.show(url); this.cover = url; });

    ui.weavingProgress(1); // the whole story is here: the thread is complete
    setTimeout(() => {
      if (this.stopped) return;
      ui.hideWeaving();
      document.body.dataset.view = "stage";
      ui.titleCard(true, o.title, o.logline);
    }, 700); // a moment to see the finished thread
    this.enqueue({ kind: "title", speaker: "narrator", delivery: "warm", text: `${o.title.replace(/[.!?]+$/, "")}.`, music: o.opening_music });
    const lines = sentences(o.opening, 1).map((text, i) => ({ kind: "line", speaker: "narrator", delivery: "warm", text, segment: 0, i, of: 0 }));
    lines.forEach((line, i, all) => { line.of = all.length; });
    this.engine.prefetch([this.queue.at(-1), ...lines].filter((x) => x?.kind === "title" || x?.kind === "line"));
    this.enqueue(...lines);
  }

  /** The whole story: bible, cast, every part and both endings of the choice. */
  onPlan(plan) {
    this.plan = plan;
    const bible = (this.bible = plan.bible);
    this.characters = bible.characters;
    this.engine.assign(plan.cast, this.deviceVoices);
    this.engine.fallback?.assign(plan.cast, this.deviceVoices);
    this.visuals.configure(bible);
    ui.renderTimeline(bible.chapters);
    ui.renderBible(bible, plan);
    const endings = Object.keys(plan.branches || {}).length;
    this.note("storyteller", `${this.notesFor("storyteller")}<br>The whole story in one pass: opening + ${bible.chapters.length} part(s) on the Story Spine (${bible.chapters.map((c) => ui.esc(c.beat.split("/")[0].trim())).join(" → ")})${endings ? `, a choice and <b>both</b> endings` : ""}, ${bible.characters.length} characters. Theme: ${ui.esc(bible.theme)}.`);
    this.note("editor", "Checked every line and picture description for this audience (lexicon + reading level) — no model call needed.");
    this.note("casting", ["narrator", ...bible.characters.map((c) => c.id)].map((id) =>
      `${id === "narrator" ? "Narrator" : ui.esc(this.characters.find((c) => c.id === id)?.name || id)} → <b>${ui.esc(this.engine.label(id) || "voice")}</b>`).join(" · "));

    ui.renderCast(this.characters, this.visuals.portraits);
    this.visuals.onStat = (s) => this.note("illustrator", `${s.done} of ${this.plan.shape?.pictures ?? "?"} pictures painted (${Object.entries(s.providers).map(([k, v]) => `${v}× ${ui.esc(k)}`).join(", ")}), avg ${(s.ms.reduce((a, b) => a + b, 0) / Math.max(1, s.ms.length) / 1000).toFixed(1)} s each${s.failed ? `, ${s.failed} painted in the browser (no image model available)` : ""}. A fixed budget of one picture per minute keeps every story inside the free tiers; every character's look is written into each picture so they stay recognisable.`);

    if (plan.shelf) ui.toast("The free models are busy right now — so here is one of StoryWeaver's own stories.", "", 7000);
    // everything is already written: adopt every part, and both endings under their choice
    const ahead = this.queuedSeconds();
    (plan.chapters || []).forEach((res, i) => this.adopt(i, "", res, ahead));
    const first = plan.chapters?.[0]?.script;
    for (const option of first?.choices || []) {
      const ending = plan.branches?.[option.keyword];
      if (ending) this.adopt(1, this.choiceNote(0, option), ending, ahead);
    }
    this.enqueue({ kind: "chapter", index: 0, note: "" });
  }

  /** Take a written part into the story: its pictures are requested with their real deadlines (a path not yet
   *  chosen costs no picture) and its first lines are pre-voiced. Replaces an earlier version (a wish). */
  adopt(index, note, res, deadline = 0) {
    const key = `${index}|${note}`;
    this.versions = (this.versions || 0) + 1;
    res.key = `${key}#${this.versions}`;
    res.readyAt = performance.now();
    const startOf = [];
    res.script.lines.reduce((sum, line, i) => { startOf[i] = sum; return sum + words(line.text) / WORDS_PER_SECOND + 0.3; }, 0);
    const plan = this.bible.chapters[index] || this.bible.chapters.at(-1);
    if (!note.includes("chose:")) {
      res.script.shots.forEach((shot, k) => this.visuals.request(`${res.key}|shot${k}`,
        this.visuals.sceneSpec(shot.description, this.visuals.charactersIn(shot), deadline + (startOf[shot.line] || 0),
          { ambience: plan.ambience, mood: plan.music }), k === 0 ? 2 : 3));
    }
    // voice the main path at once, in story order; the endings wait until their choice comes near (see beginChapter)
    if (!note.includes("chose:")) this.engine.prefetch(res.script.lines.map((l) => ({ ...l })));
    const label = note ? (note.match(/chose: "([^"]+)"/)?.[1] || "") : "";
    this.note("narrator", `${this.notesFor("narrator")}Part ${index + 1}${label ? ` (if “${ui.esc(label)}”)` : ""}: <b>${res.words}</b> words · reading grade <b>${res.grade ?? "–"}</b><br>`);
    const promise = Promise.resolve(res);
    promise.started = performance.now();
    this.prepared.set(key, promise);
    return promise;
  }

  /** Roughly how long the speech already queued will take: the time a lookahead chapter has to get ready. */
  queuedSeconds() {
    return this.queue.reduce((sum, item) => sum + (item.text ? words(item.text) / WORDS_PER_SECOND + 0.3 : 0), 0);
  }

  // ===================================================================================== chapters
  choiceNote(index, option) {
    return `At the end of chapter ${index + 1} the listener chose: "${option.label}". Continue along this choice.`;
  }

  steerNote() {
    return this.steers.length ? `While listening they asked: ${this.steers.join("; ")}. Weave this in if it fits and stays gentle.` : "";
  }

  prepare(index, note, deadline = 0) {
    const key = `${index}|${note}`;
    if (!this.prepared.has(key)) {
      const body = { request: this.request, bible: this.bible, index, summaries: this.summaries.slice(0, index),
        facts: this.facts.slice(-16), listener_note: note, lore: this.plan.lore || [], deadline_s: Math.round(deadline) };
      const label = note ? (note.match(/chose: "([^"]+)"/)?.[1] || "with your wish") : "";
      // only reached if a part is missing: write it with the chapter graph, then adopt it
      const promise = streamNDJSON("/api/chapter", body, (e) => this.onEvent(e, "chapter", label ? `branch: ${label}` : ""), this.controller.signal)
        .then((res) => this.adopt(index, note, res, deadline));
      promise.catch(() => this.prepared.delete(key));
      promise.started = performance.now();
      this.prepared.set(key, promise);
    }
    return this.prepared.get(key);
  }

  notesFor(id) {
    const text = this.did[id]?.text || "";
    return text.split("<br>").slice(-6).join("<br>");
  }

  async beginChapter(index, note) {
    let result;
    const waitStart = performance.now();
    let waited = false;
    const timer = setTimeout(() => { waited = true; this.showWaiting(); }, 400);
    for (let attempt = 0; attempt < 2 && !result; attempt++) {
      try { result = await this.prepare(index, note); } catch (err) {
        if (this.stopped) return;
        ui.toast(`Chapter ${index + 1} needs another moment… (${err.message})`, "", 4000);
        await sleep(2500);
      }
    }
    clearTimeout(timer);
    if (this.stopped) return;
    if (!result) return this.finale(true);
    const gap = performance.now() - waitStart;
    this.metrics.gaps.push(gap);
    if (!waited) this.metrics.readyAhead += 1;
    this.metrics.chapters += 1;
    this.current = index;
    this.segment = index + 1;
    const script = result.script;
    this.scripts[index] = script;
    this.summaries[index] = script.summary;
    this.facts = [...this.facts, ...script.facts].slice(-16);
    if (note === this.steerNote() && note) this.steers = [];

    const plan = this.bible.chapters[index];
    ui.titleCard(false);
    ui.setTitles(undefined, `Chapter ${index + 1} of ${this.bible.chapters.length} · ${plan.title}`);
    this.scape.set(plan.ambience, plan.tension);
    this.score.set(plan.music, plan.tension);
    this.visuals.setMood(plan.music);
    this.visuals.setAmbience(plan.ambience);
    this.note("sound", `${this.notesFor("sound")}Ch.${index + 1}: <b>${plan.ambience.join(" + ")}</b>${script.lines.some((l) => l.sfx) ? ` · effects: ${script.lines.filter((l) => l.sfx).map((l) => l.sfx).join(", ")}` : ""}<br>`);
    this.note("composer", `${this.notesFor("composer")}Ch.${index + 1}: <b>${plan.music}</b>, tension ${Math.round(plan.tension * 10)}/10<br>`);

    // pictures not painted ahead (the later scenes of the path just chosen): request them now, with real deadlines
    let at = 0;
    const startOf = script.lines.map((l) => { const s = at; at += words(l.text) / WORDS_PER_SECOND + 0.3; return s; });
    script.shots.forEach((shot, k) => this.visuals.request(`${result.key}|shot${k}`, this.visuals.sceneSpec(shot.description,
      this.visuals.charactersIn(shot), startOf[shot.line] || 0, { ambience: plan.ambience, mood: plan.music }), k === 0 ? 1 : 2));
    this.engine.prefetch(script.lines); // already cached for the main path; the chosen ending's lines start now
    for (const option of script.choices) { // both endings: their opening lines, so either choice speaks at once
      this.prepared.get(`${index + 1}|${this.choiceNote(index, option)}`)?.then((res) => this.engine.prefetch(res.script.lines.slice(0, 4)));
    }
    const shotAt = new Map(script.shots.map((s, k) => [s.line, k]));
    const items = script.lines.map((l, i) => ({ kind: "line", ...l, segment: index + 1, i, of: script.lines.length,
      shot: shotAt.has(i) ? `${result.key}|shot${shotAt.get(i)}` : null }));
    this.queue.unshift(...items, { kind: "chapter-end", index });

    this.note("director", script.choices.length
      ? `Part ${index + 1} is playing; <b>both</b> endings are ready, so whichever you choose continues at once.`
      : `Part ${index + 1} is playing — everything was written before the story began, so nothing waits.`);
  }

  showWaiting() {
    const spans = ui.showCaption({ name: "StoryWeaver", text: "The next part of the story is taking shape…", color: "#f7c873", avatar: "✦" });
    ui.highlightFraction(spans, 1);
  }

  async endChapter(index) {
    const script = this.scripts[index];
    if (index + 1 >= this.bible.chapters.length) return this.finale(false);
    if (script.choices.length) {
      const option = await this.choose(index, script.choices);
      if (this.stopped) return;
      this.decisions.push(option.label);
      this.queue.unshift({ kind: "chapter", index: index + 1, note: this.choiceNote(index, option) });
    } else {
      this.queue.unshift({ kind: "chapter", index: index + 1, note: "" });
    }
  }

  choose(index, choices) {
    return new Promise((resolve) => {
      const plan = this.bible.chapters[index];
      let done = false;
      const ctl = ui.showChoices({ question: plan.choice?.question, options: choices, timeout: this.request.audience === "kids" ? 30 : 25 },
        (keyword, auto) => {
          if (done) return;
          done = true;
          const option = choices.find((c) => c.keyword === keyword) || choices[0];
          ctl.mark(option.keyword);
          ctl.close();
          this.pick = null;
          ui.toast(auto ? `The story chose: ${option.label}` : `You chose: ${option.label}`, "good");
          ui.logEvent("listener", "listener", `${auto ? "timeout →" : "chose"} “${option.label}”`, "", performance.now() - this.t0);
          resolve(option);
        });
      this.pick = (keyword) => ctl && document.querySelector(`#choice-cards [data-k="${CSS.escape(keyword)}"]`)?.click();
      this.choiceOpen = choices;
      const next = this.bible.chapters[index + 1] || plan;
      for (const option of choices) {
        // a painted preview costs nothing; the real picture is only made for the path that is chosen
        ctl.setImage(option.keyword, this.visuals.paint({ ambience: next.ambience, mood: next.music, seed: option.label }));
        this.prepare(index + 1, this.choiceNote(index, option)).catch(() => {});
      }
    }).finally(() => { this.choiceOpen = null; });
  }

  async finale(early) {
    const bible = this.bible;
    this.segment = this.bible.chapters.length + 1;
    ui.setProgress(this.segment, 1, this.timeText());
    this.score.theme(bible.title, this.bible.chapters.at(-1)?.music);
    if (early) await this.speak({ kind: "host", speaker: "host", delivery: "warm", text: "Let's pause our story here for now." });
    await this.speak({ kind: "host", speaker: "host", delivery: "warm", text: GOODBYES[this.request.audience](bible.title) });
    this.score.set("calm", 0.1);
    this.scape.set(["wind"], 0.1);
    const minutes = (performance.now() - (this.storyStart || this.t0)) / 60000;
    const gaps = this.metrics.gaps.slice(1);
    ui.showEnd({
      title: bible.title, logline: bible.logline, cover: this.cover || "",
      stats: [`${minutes.toFixed(1)} minutes`, n(this.metrics.chapters, "part"), n(this.visuals.stats.done, "picture"),
        n(bible.characters.length, "character"), n(this.metrics.llm, "model call"),
        gaps.length ? `${Math.round(gaps.reduce((a, b) => a + b, 0) / gaps.length)} ms average wait between parts` : ""].filter(Boolean),
      choices: this.decisions,
    });
    this.updateNumbers();
  }

  // ===================================================================================== listener input
  async heard(text, intent) {
    ui.logEvent("listener", "listener", `said “${text}”`, intent.kind, performance.now() - this.t0);
    this.note("ear", `${this.notesFor("ear")}“${ui.esc(text)}” → <b>${intent.kind}</b><br>`);
    if (intent.kind === "choice" && this.choiceOpen) return this.pick?.(intent.choice_keyword);
    if (intent.kind === "steer" && intent.steer) return this.wish(intent.steer);
    if (intent.kind === "question" && intent.answer) {
      this.queue.unshift({ kind: "aside", speaker: "narrator", delivery: "warm", text: intent.answer });
      return this.wake();
    }
    ui.toast("Sorry, I didn't quite catch that.", "");
  }

  /** A spoken wish rewrites the story from the next sentence on — the rest of the part being told, the choice and
   *  both endings — with one model call while the story keeps playing: the host answers at once, the next sentence
   *  plays, then the new lines take over (with a picture of the wish coming true). If it is too late or anything
   *  fails, the story continues exactly as it was: a wish can never cause a pause. */
  async wish(steer) {
    const kind = { kind: "aside", speaker: "host", delivery: "warm" };
    if (!this.plan || !this.bible) { ui.toast("Hold that thought — the story is still being woven.", "", 3500); return; }
    const seg = this.segment; // 0: the opening, 1: the first part, 2: an ending
    const pending = this.queue.filter((it) => it.kind === "line" && it.segment === seg);
    const hasChoice = Boolean((this.scripts[0] || this.plan.chapters?.[0]?.script)?.choices?.length);
    let part, fresh, keep;
    if (seg === 0) { part = 0; fresh = true; keep = pending; } // the first part has not begun: rewrite it whole
    else if (seg === 1 && !pending.length && hasChoice) { part = 1; fresh = true; keep = []; } // at the choice: both endings
    else { part = seg - 1; fresh = false; keep = pending.slice(0, 1); } // mid-part: continue after the next sentence
    if (this.wishing || seg > this.bible.chapters.length || (!fresh && !pending.length)) {
      this.queue.unshift({ ...kind, text: "What a lovely idea! Let's keep it for our next story." });
      return this.wake();
    }
    this.wishing = true;
    this.queue.unshift({ ...kind, text: ACKS[this.request.audience] });
    this.wake();
    ui.toast(`Got it — weaving in: “${steer}”…`, "good");
    ui.logEvent("agent", "storyteller", `▸ rewriting the story from the next sentence on, with the wish “${steer}”`, "", performance.now() - this.t0);
    const told = [...this.toldLines, ...keep.map((it) => it.text)].join(" ").slice(-7500);
    const remaining = pending.slice(keep.length).reduce((sum, it) => sum + words(it.text), 0);
    const chosen = seg >= 2 ? this.decisions.at(-1) || "" : "";
    try {
      const res = await postJSON("/api/revise", { request: this.request, bible: this.bible, told, wish: steer, part, fresh,
        remaining_words: remaining, chosen }, this.controller.signal);
      if (this.stopped) return;
      if (this.segment !== seg) throw new Error("the story had already moved on");
      if (!fresh && !this.queue.some((it) => it.kind === "chapter-end" && it.index === part)) throw new Error("that part had already ended");
      const parts = res.chapters;
      const ahead = this.queuedSeconds();
      if (fresh && part === 1) { // both endings, rewritten while the choice is open
        this.scripts[0].choices.forEach((option, k) => parts[k] && this.adopt(1, this.choiceNote(0, option), parts[k], ahead));
      } else {
        if (fresh) this.adopt(0, "", parts[0], ahead); // the first part, before it begins
        else this.continueWith(seg, part, parts[0], keep);
        if (parts.length === 3) { // the choice now follows the wish: new options, new question, both endings
          const options = parts[0].script.choices;
          options.forEach((option, k) => this.adopt(1, this.choiceNote(0, option), parts[k + 1], ahead));
          this.bible.chapters[0].choice = { question: res.question || this.bible.chapters[0].choice?.question || "What should happen next?",
            options: options.map((o) => o.label) };
        }
      }
      this.welcome(res.characters, steer, parts);
      ui.toast("✓ The story now follows your wish.", "good");
      ui.logEvent("agent", "storyteller", "✓ wish woven in — the story continues with it", "", performance.now() - this.t0);
      this.note("storyteller", `${this.notesFor("storyteller")}<br>Wish “${ui.esc(steer)}” woven in from the next sentence on.`);
    } catch (err) {
      if (this.stopped) return;
      if (this.segment === seg && this.queue.some((it) => it.kind === "line")) { // say so, rather than leave it hanging
        this.queue.unshift({ ...kind, text: "The story crew is busy right now, so let's keep that idea for our next story." });
        this.wake();
      }
      ui.toast("The story continues as it was.", "");
      ui.logEvent("warn", "storyteller", `wish not applied (${err.message})`, "", performance.now() - this.t0);
    } finally {
      this.wishing = false;
    }
  }

  /** Whoever a wish brings into the story joins the cast on the right: the Storyteller names them; if it names no
   *  one, the wish and the new lines do ("add a friendly firefly" + "…a firefly named Luma…" → Luma, friendly firefly). */
  welcome(characters, steer, parts = []) {
    let newcomers = (characters || []).filter((c) => c?.name);
    const guess = !newcomers.length && newcomerIn(steer);
    if (guess) {
      const known = new Set((this.characters || []).map((c) => c.name.toLowerCase()));
      const text = parts.flatMap((p) => p.script?.lines || []).map((l) => l.text).join(" ");
      const named = newName(text, known);
      if (named) { guess.description ||= guess.name; guess.name = named; }
      newcomers = [guess];
    }
    for (const c of newcomers) {
      const id = `wish-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
      if (this.characters?.some((k) => k.name.toLowerCase() === c.name.toLowerCase())) continue;
      if (!ui.addToCast({ id, name: c.name, emoji: c.emoji || "✨", role: c.description || "From your wish", description: c.description })) continue;
      ui.logEvent("agent", "storyteller", `+ ${c.name} joins the story`, c.description || "", performance.now() - this.t0);
      this.note("casting", `${this.notesFor("casting")}<br><b>${ui.esc(c.name)}</b> joined from your wish (voiced through the narrator).`);
    }
  }

  /** Replace the rest of the part being told with its rewritten continuation (after the sentence kept playing). */
  continueWith(seg, part, res, keep) {
    const script = res.script;
    const kept = new Set(keep);
    this.queue = this.queue.filter((it) => !(it.kind === "line" && it.segment === seg && !kept.has(it)));
    let at = this.queue.findIndex((it) => it.kind === "chapter-end" && it.index === part);
    if (at < 0) at = this.queue.length;
    const before = this.queue.slice(0, at).reduce((sum, it) => sum + (it.text ? words(it.text) / WORDS_PER_SECOND + 0.3 : 0), 0);
    const last = keep.at(-1) || (this.lastLine?.segment === seg ? this.lastLine : null);
    const offset = last ? last.i + 1 : 0;
    this.versions = (this.versions || 0) + 1;
    const key = `wish${this.versions}`;
    const plan = this.bible.chapters[part] || this.bible.chapters.at(-1);
    const startOf = [];
    script.lines.reduce((sum, line, i) => { startOf[i] = sum; return sum + words(line.text) / WORDS_PER_SECOND + 0.3; }, 0);
    const shotAt = new Map(script.shots.map((s, k) => [s.line, k]));
    script.shots.forEach((shot, k) => this.visuals.request(`${key}|shot${k}`, this.visuals.sceneSpec(shot.description,
      this.visuals.charactersIn(shot), before + (startOf[shot.line] || 0), { ambience: plan.ambience, mood: plan.music }), 1));
    const items = script.lines.map((l, i) => ({ kind: "line", ...l, segment: seg, i: offset + i, of: offset + script.lines.length,
      shot: shotAt.has(i) ? `${key}|shot${shotAt.get(i)}` : null }));
    this.engine.prefetch(items);
    this.queue.splice(at, 0, ...items);
    const old = this.scripts[part];
    if (old) {
      const heard = old.lines.slice(0, offset);
      this.scripts[part] = { ...old, lines: [...heard, ...script.lines], summary: script.summary,
        choices: script.choices.length ? script.choices : old.choices };
    }
  }

  context() {
    return { audience: this.request.audience, choices: this.choiceOpen || [], summaries: this.summaries.filter(Boolean) };
  }

  async typed(text) {
    const intent = await postJSON("/api/interpret", { text, ...this.context() });
    return this.heard(text, intent);
  }

  // ===================================================================================== playback
  async play(item) {
    switch (item.kind) {
      case "chapter": return this.beginChapter(item.index, item.note ?? "");
      case "chapter-end": return this.endChapter(item.index);
      case "title":
        this.score.theme(this.title, item.music);
        return this.speak(item);
      default: return this.speak(item);
    }
  }

  async speak(item) {
    if (this.stopped) return;
    if (item.shot) this.visuals.cache.get(item.shot)?.then((url) => { if (url && this.segment === item.segment) this.visuals.show(url); });
    if (item.segment === 0 && item.i === 0) this.opening?.then((url) => url && this.visuals.show(url));
    if (item.segment === 0 && item.i === 1) ui.titleCard(false); // the title has had its moment: show the world
    const character = this.characters?.find((c) => c.id === item.speaker);
    const name = item.speaker === "host" ? "StoryWeaver" : item.speaker === "narrator" ? "Narrator" : character?.name || item.speaker;
    const portrait = this.visuals.portraits.get(item.speaker)?.url;
    const spans = ui.showCaption({ name, delivery: item.kind === "line" ? item.delivery : "", text: item.text,
      color: ui.speakerColor(item.speaker, this.characters || []), avatar: portrait || (item.speaker === "host" ? "✦" : item.speaker === "narrator" ? "📖" : "🙂") });
    ui.setSpeaking(item.speaker);
    if (item.sfx) { this.scape.sfx(item.sfx); this.metrics.sfx += 1; }
    if (this.metrics.firstAudio === undefined) this.metrics.firstAudio = performance.now() - this.t0;
    if ((item.kind === "line" || item.kind === "title") && this.metrics.firstStory === undefined) {
      this.metrics.firstStory = performance.now() - this.t0;
      this.storyStart = performance.now();
    }
    if (item.segment !== undefined) ui.setProgress(item.segment, (item.i + 1) / Math.max(1, item.of), this.timeText());
    if (item.kind === "line") { this.toldLines.push(item.text); this.lastLine = item; }
    this.mixer.duck(true);
    let raf = null;
    const startedAt = performance.now();
    await this.engine.speak(item, {
      onStart: (seconds) => {
        if (this.engine.name === "device") return; // device voices report word boundaries instead
        const tick = () => { ui.highlightFraction(spans, (performance.now() - startedAt) / 1000 / seconds); raf = requestAnimationFrame(tick); };
        raf = requestAnimationFrame(tick);
      },
      onBoundary: (charIndex) => ui.highlightToChar(spans, charIndex),
    });
    if (raf) cancelAnimationFrame(raf);
    this.mixer.duck(false);
    ui.highlightFraction(spans, 1);
    if (this.paused && !this.stopped) { this.queue.unshift(item); return; } // replay the interrupted line on resume
    this.updateNumbers();
    await sleep(item.kind === "line" ? 260 : 420);
  }

  timeText() {
    const elapsed = this.storyStart ? (performance.now() - this.storyStart) / 1000 : 0;
    return `${fmt(elapsed)} / ~${this.request.minutes}:00`;
  }

  updateNumbers() {
    const m = this.metrics;
    const gaps = m.gaps.slice(1);
    ui.renderNumbers({
      "Voice engine": `${this.engineInfo.engine} (${this.engineInfo.why})`,
      "Time to first sound (the host)": m.firstAudio !== undefined ? `${(m.firstAudio / 1000).toFixed(1)} s` : "–",
      "Whole story written and checked": this.openingAt !== undefined ? `${(this.openingAt / 1000).toFixed(1)} s` : "–",
      "Time until the story begins": m.firstStory !== undefined ? `${(m.firstStory / 1000).toFixed(1)} s` : "–",
      "Story parts written before narration": this.prepared.size ? `all ${this.prepared.size} (both endings included)` : "–",
      "Parts ready the moment they were needed": m.chapters ? `${Math.max(0, m.readyAhead)} of ${m.chapters} so far` : "–",
      "Average wait between parts": gaps.length ? `${Math.round(gaps.reduce((a, b) => a + b, 0) / gaps.length)} ms` : "–",
      "Agent model calls": m.llm,
      "Tokens used": m.tokens.toLocaleString(),
      "Calls that needed a fallback": m.fallbacks,
      "Pictures painted": `${this.visuals.stats.done}${this.visuals.stats.failed ? ` (+${this.visuals.stats.failed} fell back)` : ""}`,
      "Sound effects cued": m.sfx,
      "Listener choices": this.decisions.length,
    });
  }
}
