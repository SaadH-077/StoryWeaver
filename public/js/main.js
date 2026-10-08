// StoryWeaver web client — boot, the home screen, and wiring between the Director and the controls.
import { getJSON } from "./api.js";
import { Mixer } from "./audio/mixer.js";
import { Score } from "./audio/score.js";
import { Soundscape } from "./audio/soundscape.js";
import { Director, GREETINGS } from "./director.js";
import { renderHowItWorks } from "./howitworks.js";
import { PushToTalk } from "./ptt.js";
import { startStars } from "./stars.js";
import * as ui from "./ui.js";
import { chooseEngine, DeviceEngine, loadDeviceVoices, ServerEngine, SimEngine } from "./voices.js";
import { Visuals } from "./visuals.js";

const { $ } = ui;
const HOST = { kokoro: "af_heart", gemini: "Sulafat", edge: "en-US-AvaNeural", gender: "female", age: "adult", accent: "american", speed: 1, pitch: 1, persona: "the friendly StoryWeaver host" };
const NARRATOR = { kokoro: "bf_emma", gemini: "Kore", edge: "en-GB-SoniaNeural", gender: "female", age: "adult", accent: "british", speed: 0.97, pitch: 1 };
const LENGTH_NOTES = {};
const S = { audience: "family", minutes: "2", config: null, health: null, devices: [], director: null, mixer: null, visuals: null };

// ------------------------------------------------------------------------------------------------ boot
async function boot() {
  startStars($("#stars"));
  bindOptions("#audience", "audience", "family");
  bindOptions("#length", "minutes", "2", updateLengthNote);
  document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openModal(b.dataset.open)));
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => closeModal(b.dataset.close)));
  $("#story-form").addEventListener("submit", (e) => { e.preventDefault(); begin(); });
  $("#surprise").addEventListener("click", surprise);
  $("#engine").addEventListener("change", () => { updateVoiceNote(); warmGreetings(); });
  bindStageControls();
  bindStartMic();
  $("#hero").addEventListener("input", updateNamePreview);
  try {
    [S.config, S.health, S.devices] = await Promise.all([getJSON("/api/config"), getJSON("/api/health"), loadDeviceVoices()]);
  } catch (err) {
    $("#status-line").innerHTML = `<span class="warn">The StoryWeaver server isn't reachable (${ui.esc(err.message)}).</span>`;
    return;
  }
  $("#examples").innerHTML = S.config.examples.map((e) => `<button type="button" class="chip" data-text="${ui.esc(e.text)}">${e.emoji} ${ui.esc(e.text)}</button>`).join("");
  document.querySelectorAll("#examples .chip").forEach((c) => c.addEventListener("click", () => { $("#prompt").value = c.dataset.text; $("#prompt").focus(); }));
  for (const l of S.config.lengths) LENGTH_NOTES[l.minutes] = l;
  updateLengthNote();
  updateVoiceNote();
  const h = S.health;
  const ok = (b) => (b ? '<span class="ok">●</span>' : '<span class="warn">●</span>');
  $("#status-line").innerHTML = `<span>${ok(h.llm.groq)} Agents ${h.llm.gemini ? "(+ Gemini fallback)" : ""}</span>
    <span>${ok(h.images.length)} Pictures: ${ui.esc(h.images[0] || "off")}</span>
    <span>${ok(true)} Voices: ${S.devices.length} on this device${h.voices.neural?.available ? " · neural" : ""}${h.voices.studio.available ? " · studio" : ""}</span>
    <span>${ok(h.voice_input)} Voice input</span>`;
  $("#begin").disabled = !h.ok; // enabled only once everything is ready (an early click would do nothing)
  renderHowItWorks();
  warmGreetings();
  rotatePlaceholder();
}

function bindOptions(group, key, initial, onChange) {
  const buttons = [...document.querySelectorAll(`${group} .option`)];
  const select = (value) => {
    S[key] = value;
    buttons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.value === value)));
    onChange?.();
  };
  buttons.forEach((b) => b.addEventListener("click", () => select(b.dataset.value)));
  select(initial);
}

function updateLengthNote() {
  const l = LENGTH_NOTES[S.minutes];
  if (!l) return;
  const plural = (n, word) => `<b>${n}</b> ${word}${n === 1 ? "" : "s"}`;
  $("#length-note").innerHTML = `About <b>${l.minutes} minute${l.minutes > 1 ? "s" : ""}</b>: an opening and ${plural(l.chapters, "chapter")}, `
    + `${l.choices ? `${plural(l.choices, "moment")} where you decide` : "no choices (just listen)"}, and ${plural(l.pictures, "picture")}.`;
}

/** While the listener is still typing, have the server voice the greetings once (it caches them), so the first
 *  sound after "Weave my story" is instant even with server voices. */
function warmGreetings() {
  const info = chooseEngine($("#engine").value, S.health, S.devices);
  if (!["neural", "cloud", "studio"].includes(info.engine)) return;
  for (const text of Object.values(GREETINGS)) {
    fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice: HOST, delivery: "warm", engine: info.engine }) }).catch(() => {});
  }
}

function updateNamePreview() {
  const name = $("#hero").value.trim().replace(/[^\p{L}\p{M}' -]/gu, "").slice(0, 24);
  $("#name-preview").innerHTML = name
    ? `“Once upon a time, there lived a hero called <b>${ui.esc(name)}</b>…”`
    : "“Once upon a time, there lived a hero called <b>…</b>”";
}

function updateVoiceNote() {
  if (!S.health) return;
  const info = chooseEngine($("#engine").value, S.health, S.devices);
  const names = { device: "Device voices", neural: "Neural voices", studio: "Studio voices (Kokoro)", cloud: "Expressive voices (Gemini)" };
  $("#voice-note").textContent = `→ ${names[info.engine] || info.engine}: ${info.why}.`;
}

function rotatePlaceholder() {
  const ideas = S.config.examples.map((e) => e.text);
  let i = 0;
  setInterval(() => { if (!$("#prompt").value) $("#prompt").placeholder = `A story about… ${ideas[i++ % ideas.length].toLowerCase()}`; }, 3500);
}

function surprise() {
  const ideas = ["A cloud who wants to learn how to rain", "A tiny robot who repairs broken dreams", "The penguin who wanted to fly to the moon",
    "A library where the books whisper at night", "A grandmother who knits maps of places that don't exist yet", "A snail who enters the great forest race",
    "A lost star who lands in a fishing village", "The lighthouse that learned to sing"];
  $("#prompt").value = ideas[Math.floor(Math.random() * ideas.length)];
  $("#prompt").focus();
}

function openModal(id) { $(`#${id}`).hidden = false; document.body.classList.add("modal-open"); }
function closeModal(id) { $(`#${id}`).hidden = true; document.body.classList.remove("modal-open"); }

// ------------------------------------------------------------------------------------------------ story
async function begin(promptOverride) {
  const prompt = (promptOverride || $("#prompt").value).trim();
  if (prompt.length < 2) { $("#prompt").focus(); return; }
  $("#begin").disabled = true;
  try {
    resetStage();
    const request = { prompt, audience: S.audience, minutes: Number(S.minutes), hero_name: $("#hero").value.trim() || null };
    // audio must start inside this user gesture
    const mixer = (S.mixer = new Mixer());
    await mixer.init();
    mixer.setMusic(Number($("#vol-music").value));
    mixer.setAmbience(Number($("#vol-amb").value));
    const scape = new Soundscape(mixer);
    const score = new Score(mixer);
    scape.set(["wind"], 0.15);
    score.set("calm", 0.12);
    const simulated = new URLSearchParams(location.search).get("voices") === "sim"; // automated UI test
    const info = simulated ? { engine: "simulated", why: "test mode: silent voices that keep real-time pace" }
      : chooseEngine($("#engine").value, S.health, S.devices);
    const device = simulated ? new SimEngine(request.audience) : new DeviceEngine(request.audience);
    const engine = info.engine === "device" || simulated ? device : new ServerEngine(info.engine, mixer, device);
    const provisional = { host: HOST, narrator: NARRATOR };
    engine.assign(provisional, S.devices);
    device.assign(provisional, S.devices);
    S.visuals = new Visuals({ shotA: $("#shot-a"), shotB: $("#shot-b"), painted: $("#painted"), particles: $("#particles") });
    S.director = new Director({ request, length: LENGTH_NOTES[S.minutes], engine, engineInfo: info, mixer, scape, score, visuals: S.visuals,
      onExit: (idea) => goHome(idea) });
    S.director.deviceVoices = S.devices;
    S.director.start();
  } finally {
    $("#begin").disabled = false;
  }
}

function resetStage() {
  ["#endcard", "#refusal", "#choices"].forEach((s) => { $(s).hidden = true; });
  ui.hideCaption();
  ui.titleCard(false);
  ui.setTitles("StoryWeaver", "");
  $("#tl-segs").innerHTML = "";
  $("#tl-time").textContent = "";
  $("#cast-strip").innerHTML = "";
  $("#log").innerHTML = "";
  $("#tab-safety").innerHTML = "";
  $("#tab-bible").innerHTML = '<p class="muted">The Storyteller hasn\'t written the story yet.</p>';
  ui.renderNumbers({});
  document.body.classList.remove("paused");
}

async function goHome(idea) {
  S.director?.stop();
  S.director = null;
  await S.mixer?.close();
  S.mixer = null;
  S.visuals?.clear();
  ui.hideWeaving();
  ui.closeDrawer();
  document.body.dataset.view = "home";
  if (idea) { $("#prompt").value = idea; begin(idea); }
}

// ------------------------------------------------------------------------------------------------ controls
function bindStageControls() {
  $("#home-btn").addEventListener("click", () => goHome());
  $("#again-btn").addEventListener("click", () => goHome());
  $("#refusal-back").addEventListener("click", () => goHome());
  $("#end-crew").addEventListener("click", () => { ui.renderCrew(S.director?.did || {}, new Set()); ui.openDrawer("crew"); });
  $("#crew-btn").addEventListener("click", () => {
    if ($("#drawer").hidden) { ui.renderCrew(S.director?.did || {}, S.director?.live || new Set()); ui.openDrawer(); }
    else ui.closeDrawer();
  });
  $("#drawer-close").addEventListener("click", ui.closeDrawer);
  document.querySelectorAll(".drawer .tabs button").forEach((b) => b.addEventListener("click", () => {
    ui.selectTab(b.dataset.tab);
    if (b.dataset.tab === "crew") ui.renderCrew(S.director?.did || {}, S.director?.live || new Set());
  }));
  $("#pause-btn").addEventListener("click", togglePause);
  $("#cc-btn").addEventListener("click", () => document.body.classList.toggle("no-captions"));
  $("#vol-music").addEventListener("input", (e) => S.mixer?.setMusic(Number(e.target.value)));
  $("#vol-amb").addEventListener("input", (e) => S.mixer?.setAmbience(Number(e.target.value)));

  const ptt = new PushToTalk({
    button: $("#ptt"),
    onState: (state) => {
      $("#ptt").classList.toggle("rec", state === "recording");
      $("#ptt").classList.toggle("busy", state === "sending");
      $("#ptt-label").textContent = { recording: "Listening…", sending: "Thinking…" }[state] || "Hold to talk";
      if (state === "denied") ui.toast("Microphone permission was denied.", "warn");
      if (state === "unsupported") ui.toast("Voice input isn't supported in this browser.", "warn");
      if (state === "too-short") ui.toast("Hold the button while you speak.", "");
    },
    onAudio: async (blob) => {
      try {
        const res = await listen(blob, S.director?.context());
        if (res.transcript) await S.director?.heard(res.transcript, res.intent);
        else ui.toast("I didn't hear anything — hold the button while you speak.", "");
      } catch (err) { ui.toast(`Voice input failed: ${err.message}`, "warn"); }
      finally { $("#ptt").classList.remove("busy"); $("#ptt-label").textContent = "Hold to talk"; }
    },
  });
  let spaceDown = false;
  addEventListener("keydown", (e) => {
    if (e.target.matches?.("input, textarea, select")) return;
    if (e.key === "Escape") { closeModal("how"); ui.closeDrawer(); }
    if (document.body.dataset.view !== "stage") return;
    if (e.code === "Space" && !spaceDown) { e.preventDefault(); spaceDown = true; ptt.start(); }
    if (e.key === "p" || e.key === "P") togglePause();
    if (e.key === "c" || e.key === "C") document.body.classList.toggle("no-captions");
  });
  addEventListener("keyup", (e) => { if (e.code === "Space" && spaceDown) { e.preventDefault(); spaceDown = false; ptt.stop(); } });
}

async function togglePause() {
  const d = S.director;
  if (!d) return;
  if (d.paused) { await d.resume(); document.body.classList.remove("paused"); }
  else { await d.pause(); document.body.classList.add("paused"); }
}

async function listen(blob, context) {
  const fd = new FormData();
  fd.append("audio", blob, "speech.webm");
  fd.append("context", JSON.stringify(context || {}));
  const res = await fetch("/api/listen", { method: "POST", body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function bindStartMic() {
  new PushToTalk({
    button: $("#mic-start"),
    onState: (state) => {
      $("#mic-start").classList.toggle("rec", state === "recording");
      if (state === "denied") ui.toast("Microphone permission was denied.", "warn");
    },
    onAudio: async (blob) => {
      try {
        const res = await listen(blob, {});
        if (res.transcript) $("#prompt").value = res.transcript.replace(/^(please\s+)?(tell me|i want|can you tell me)?\s*(a\s+)?(story|tale)\s+(about\s+)?/i, "").replace(/[.?!]+$/, "");
      } catch (err) { ui.toast(`Voice input failed: ${err.message}`, "warn"); }
    },
  });
}

boot();
