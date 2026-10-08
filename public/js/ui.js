// DOM rendering for the stage, the weaving overlay and the crew drawer (no framework).
import { CREW, crewById, PLAN_CREW } from "./crew.js";

export const $ = (s, root = document) => root.querySelector(s);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const PALETTE = ["#62e3d2", "#ff8fb3", "#a184ff", "#82c8ff", "#9be38c", "#ffb27a"];

export function speakerColor(id, characters = []) {
  if (id === "narrator") return "#f5e6c8";
  if (id === "host") return "#f7c873";
  const idx = Math.max(0, characters.findIndex((c) => c.id === id));
  return PALETTE[idx % PALETTE.length];
}

export function toast(text, kind = "", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ------------------------------------------------------------------------------------------- weaving overlay
// What each member says while the cast assembles (the four in PLAN_CREW then report their real progress)
const JOINING = { guardian: "Checking your idea…", storyteller: "Writing the whole story…", editor: "Will check every line",
  casting: "Will cast the voices", illustrator: "Ready to paint", composer: "Tuning up", sound: "Gathering sounds",
  narrator: "Warming up the voices", director: "Taking the director's chair", ear: "Listening for you" };

/** The loading screen: the crew assembles for this story, card by card, and a thread weaves across as each stage of
 *  the story graph finishes (Guardian → Storyteller → Editor → Casting). */
export function showWeaving(prompt) {
  $("#weaving-title").textContent = "Assembling your story's crew…";
  $("#weaving-sub").textContent = `“${prompt}”`;
  $("#crew-row").innerHTML = CREW.map((c, i) => `<div class="crew-chip" data-crew="${c.id}" style="--i:${i}">
      <div class="c-ico">${c.icon}</div><div><div class="c-name">${esc(c.name)}</div><div class="c-state">Joining…</div></div></div>`).join("");
  CREW.forEach((c, i) => setTimeout(() => {
    const chip = $(`#crew-row [data-crew="${c.id}"]`);
    if (!chip || chip.classList.contains("done") || chip.classList.contains("working")) return;
    $(".c-state", chip).textContent = JOINING[c.id] || "Ready";
    chip.classList.add(PLAN_CREW.includes(c.id) ? "waiting" : "ready");
  }, 450 + i * 120));
  weavingProgress(0.06);
  $("#weaving").hidden = false;
  document.body.dataset.view = "weaving"; // nothing else renders behind the overlay (cheap on weak machines)
}

export function weavingProgress(fraction) { $("#weave-bar").style.setProperty("--p", `${Math.round(fraction * 100)}%`); }

export function crewChip(id, state, detail) {
  const chip = $(`#crew-row [data-crew="${id}"]`);
  if (!chip) return;
  chip.classList.toggle("working", state === "start" || state === "waiting");
  chip.classList.toggle("done", state === "done");
  chip.classList.toggle("warn", state === "warn");
  if (detail) $(".c-state", chip).textContent = detail.split(" (")[0]; // the short form; the log has the rest
  const done = PLAN_CREW.filter((cid) => $(`#crew-row [data-crew="${cid}"]`)?.classList.contains("done")).length;
  weavingProgress(Math.max(0.06, done / PLAN_CREW.length));
}

export function hideWeaving() { $("#weaving").hidden = true; }

// ------------------------------------------------------------------------------------------- stage
export function setTitles(title, label) {
  if (title !== undefined) $("#story-title").textContent = title;
  if (label !== undefined) $("#chapter-label").textContent = label;
}

export function titleCard(on, title = "", logline = "") {
  if (on) { $("#tc-title").textContent = title; $("#tc-logline").textContent = logline; }
  $("#titlecard").classList.toggle("on", on);
}

export function showCaption({ name, delivery, text, color, avatar }) {
  const cap = $("#caption");
  cap.style.setProperty("--spk", color);
  $("#cap-avatar").innerHTML = avatar?.startsWith("blob:") || avatar?.startsWith("data:") ? `<img src="${avatar}" alt="">` : esc(avatar || "📖");
  $("#cap-speaker").innerHTML = `${esc(name)}${delivery && delivery !== "neutral" ? `<span class="delivery">${esc(delivery)}</span>` : ""}`;
  const parts = String(text).split(/(\s+)/);
  let offset = 0;
  $("#cap-text").innerHTML = parts.map((p) => {
    const start = offset;
    offset += p.length;
    return p.trim() ? `<span class="w" data-c="${start}">${esc(p)}</span>` : p;
  }).join("");
  cap.classList.remove("hide");
  return [...document.querySelectorAll("#cap-text .w")];
}

export function highlightToChar(spans, charIndex) {
  for (const s of spans) s.classList.toggle("on", Number(s.dataset.c) <= charIndex);
}

export function highlightFraction(spans, fraction) {
  const total = spans.reduce((n, s) => n + s.textContent.length + 1, 0);
  let budget = fraction * total * 1.05;
  for (const s of spans) { budget -= s.textContent.length + 1; s.classList.toggle("on", budget >= -s.textContent.length * 0.5); }
}

export function hideCaption() { $("#caption").classList.add("hide"); }

export function renderCast(characters, portraits) {
  $("#cast-strip").innerHTML = characters.map((c) => {
    const p = portraits.get(c.id);
    return `<div class="cast-face" data-id="${esc(c.id)}" style="--spk:${speakerColor(c.id, characters)}" title="${esc(c.name)}">${p ? `<img src="${p.url}" alt="${esc(c.name)}">` : `<span>${esc((c.name || "?").trim()[0] || "?")}</span>`}</div>`;
  }).join("");
}

export function setSpeaking(id) {
  document.querySelectorAll("#cast-strip .cast-face").forEach((el) => el.classList.toggle("speaking", el.dataset.id === id));
}

// ------------------------------------------------------------------------------------------- timeline
export function renderTimeline(chapters) {
  $("#tl-segs").innerHTML = `<div class="tl-seg opening" data-seg="0"><i></i></div>` + chapters.map((c, i) =>
    `<div class="tl-seg ${c.choice ? "choice" : ""}" data-seg="${i + 1}" title="${esc(c.title)}"><i></i></div>`).join("");
}

export function setProgress(segment, fraction, timeText) {
  document.querySelectorAll("#tl-segs .tl-seg").forEach((el) => {
    const n = Number(el.dataset.seg);
    el.querySelector("i").style.width = `${n < segment ? 100 : n === segment ? Math.round(fraction * 100) : 0}%`;
  });
  if (timeText) $("#tl-time").textContent = timeText;
}

// ------------------------------------------------------------------------------------------- choices
export function showChoices({ question, options, timeout }, onPick) {
  $("#choice-q").textContent = question || "What should happen next?";
  $("#choice-cards").innerHTML = options.map((o) => `<button class="choice-card" data-k="${esc(o.keyword)}">
      <span class="cc-key">say “${esc(o.keyword)}”</span><span class="cc-label">${esc(o.label)}</span><span class="cc-ready"></span></button>`).join("");
  document.querySelectorAll("#choice-cards .choice-card").forEach((b) => b.addEventListener("click", () => onPick(b.dataset.k, false)));
  $("#choices").hidden = false;
  const ring = $("#cd");
  const started = performance.now();
  const timer = setInterval(() => {
    const left = Math.max(0, 1 - (performance.now() - started) / (timeout * 1000));
    ring.style.strokeDashoffset = String(100.5 * (1 - left));
    if (left <= 0) { clearInterval(timer); onPick(options[0].keyword, true); }
  }, 100);
  return {
    setImage(keyword, url) {
      const card = $(`#choice-cards [data-k="${CSS.escape(keyword)}"]`);
      if (card && url) card.style.setProperty("--card-bg", `url("${url}")`);
    },
    setReady(keyword) {
      const el = $(`#choice-cards [data-k="${CSS.escape(keyword)}"] .cc-ready`);
      if (el) el.textContent = "✓ this path is already written";
    },
    mark(keyword) { document.querySelectorAll("#choice-cards .choice-card").forEach((b) => b.classList.toggle("picked", b.dataset.k === keyword)); },
    close() { clearInterval(timer); setTimeout(() => { $("#choices").hidden = true; }, 650); },
  };
}

// ------------------------------------------------------------------------------------------- end + refusal
export function showEnd({ title, logline, cover, stats, choices }) {
  $("#end-title").textContent = title;
  $("#end-logline").textContent = logline;
  $("#end-cover").src = cover || "";
  $("#end-stats").innerHTML = stats.map((s) => `<span>${esc(s)}</span>`).join("");
  $("#end-choices").textContent = choices.length ? `Your choices: ${choices.join(" → ")}` : "";
  $("#endcard").hidden = false;
}

export function showRefusal(reason, ideas, onIdea) {
  $("#refusal-reason").textContent = reason;
  $("#refusal-ideas").innerHTML = ideas.map((i) => `<button class="chip">${esc(i)}</button>`).join("");
  document.querySelectorAll("#refusal-ideas .chip").forEach((c) => c.addEventListener("click", () => onIdea(c.textContent)));
  $("#refusal").hidden = false;
}

// ------------------------------------------------------------------------------------------- crew drawer
export function openDrawer(tab) {
  $("#drawer").hidden = false;
  $("#crew-btn").setAttribute("aria-expanded", "true");
  if (tab) selectTab(tab);
}
export function closeDrawer() { $("#drawer").hidden = true; $("#crew-btn").setAttribute("aria-expanded", "false"); }
export function selectTab(tab) {
  document.querySelectorAll(".drawer .tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  document.querySelectorAll(".drawer .panel").forEach((p) => { p.hidden = p.id !== `tab-${tab}`; });
}

/** Crew cards: role, model and what each agent did for *this* story. */
export function renderCrew(did, live = new Set()) {
  $("#tab-crew").innerHTML = `<p class="hint" style="margin:2px 0 12px;color:var(--text-2);font-size:13.5px">Every story is made by this crew. Here is what each of them did for yours.</p>`
    + CREW.map((c) => `<div class="agent-card ${live.has(c.id) ? "live" : ""}">
      <div class="a-ico">${c.icon}</div>
      <div><div class="a-head"><span class="a-name">${esc(c.name)}</span><span class="a-model">${esc(did[c.id]?.model || c.model)}</span></div>
      <div class="a-role">${esc(c.role)}</div>
      ${did[c.id]?.text ? `<div class="a-did">${did[c.id].text}</div>` : ""}</div></div>`).join("");
}

export function logEvent(kind, who, detail, meta = "", t) {
  const li = document.createElement("li");
  li.className = kind;
  li.innerHTML = `<span class="t">${t !== undefined ? `${(t / 1000).toFixed(1)}s` : ""}</span><span class="who">${esc(who)}</span> ${esc(detail)}${meta ? `<span class="meta">${esc(meta)}</span>` : ""}`;
  const list = $("#log");
  list.appendChild(li);
  const panel = $("#tab-log");
  if (panel.scrollHeight - panel.scrollTop - panel.clientHeight < 160) panel.scrollTop = panel.scrollHeight;
}

export function renderSafety(request, chapters) {
  const layers = request?.layers || [];
  const layerNames = { lexicon: "Deterministic lexicon", "injection classifier": "Prompt-injection classifier", "policy model": "Policy model" };
  const rows = layers.map((l, i) => `<div class="layer ${l.verdict === "block" || l.verdict === "refuse" ? "bad" : ""}">
      <div class="l-num">${i + 1}</div><div><div class="l-title">${esc(layerNames[l.layer] || l.layer)} — ${esc(l.verdict)}</div>
      <div class="l-detail">${esc(l.detail || "no issues")}${l.ms ? ` · ${l.ms} ms` : ""}</div></div></div>`).join("");
  const outputs = chapters.map((c) => `<div class="layer ${c.approved ? "" : "bad"}"><div class="l-num">${c.chapter || "✓"}</div><div>
      <div class="l-title">${c.chapter ? `Chapter ${c.chapter}` : "The whole story"}: ${c.approved ? "approved" : "revised"} · reading grade ${c.grade ?? "–"}</div>
      <div class="l-detail">${esc((c.issues || []).join(" · ") || (c.chapter ? "lexicon clean · editor approved" : "lexicon clean · reading level on target"))}</div></div></div>`).join("");
  $("#tab-safety").innerHTML = `<p class="hint" style="color:var(--text-2);font-size:13.5px">Your request went through these layers before a single word was written:</p>${rows || "<p>…</p>"}
    <p class="hint" style="color:var(--text-2);font-size:13.5px;margin-top:18px">The finished story — every part and both endings — is checked again before a word is voiced: the lexicon on every line and picture prompt, then the reading level:</p>${outputs || "<p class='l-detail'>The check appears here as soon as the story is written.</p>"}`;
}

export function renderBible(bible, plan) {
  if (!bible) return;
  const chars = bible.characters.map((c) => `<div class="beat"><b>${esc(c.name)}</b> — ${esc(c.role)}<small>${esc(c.description)} · Looks: ${esc(c.look)}</small></div>`).join("");
  const chapters = bible.chapters.map((p, i) => `<div class="beat"><b>${i + 1}. ${esc(p.title)}</b> · <i>${esc(p.beat)}</i>
      <small>${esc(p.summary)}</small><small>Freytag: ${esc(p.act.replace("_", " "))} · tension ${Math.round(p.tension * 10)}/10 · Propp: ${esc((p.propp || []).join(", ") || "–")}${p.choice ? " · listener choice" : ""}</small></div>`).join("");
  const seeds = (bible.seeds || []).map((s) => `<div class="beat">${esc(s.setup)}<small>pays off: ${esc(s.payoff || "later")}</small></div>`).join("");
  $("#tab-bible").innerHTML = `<h3>${esc(bible.title)}</h3><p>${esc(bible.logline)}</p>
    <h4>World</h4><p>${esc(bible.setting)}</p><p><i>${esc(bible.genre)} · ${esc(bible.tone)}</i></p>
    <h4>Opening (Once upon a time…)</h4><p>${esc(bible.opening)}</p>
    ${bible.hero_arc?.want || bible.hero_arc?.flaw || bible.hero_arc?.growth ? `<h4>Hero's arc</h4><p>Wants: ${esc(bible.hero_arc?.want || "–")}<br>Flaw / fear: ${esc(bible.hero_arc?.flaw || "–")}<br>Grows by: ${esc(bible.hero_arc?.growth || "–")}</p>` : ""}
    <h4>Theme</h4><p>${esc(bible.theme)}</p>
    <h4>Cast</h4>${chars}
    <h4>Story Spine × Freytag × Propp</h4>${chapters}
    ${seeds ? `<h4>Planted setups → payoffs</h4>${seeds}` : ""}
    <h4>Art direction</h4><p>${esc(bible.art_style)}</p>
    ${plan?.lore?.length ? `<h4>True facts from the Lore Scout</h4><p>${plan.lore.map(esc).join("<br>")}</p>` : ""}`;
}

export function renderNumbers(rows) {
  $("#numbers").innerHTML = Object.entries(rows).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
}
