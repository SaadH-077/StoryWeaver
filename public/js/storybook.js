// The Storybook: every story you have heard, kept in this browser with its pictures, to read again as a book.
// Stories are stored in IndexedDB (pictures as small JPEGs); if the browser refuses storage (a private window),
// they are kept for this visit only. Nothing leaves the device.
import { $, esc } from "./ui.js";

const DB = "storyweaver";
const STORE = "books";
const memory = new Map(); // used when IndexedDB is unavailable
let dbPromise = null;

function db() {
  dbPromise ||= new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch { resolve(null); }
  });
  return dbPromise;
}

async function run(mode, fn) {
  const handle = await db();
  if (!handle) return null;
  return new Promise((resolve) => {
    try {
      const tx = handle.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req?.result ?? true);
      tx.onerror = () => resolve(null);
    } catch { resolve(null); }
  });
}

export async function listBooks() {
  const stored = (await run("readonly", (s) => s.getAll())) || [];
  const all = new Map([...stored, ...memory.values()].map((b) => [b.id, b]));
  return [...all.values()].sort((a, b) => b.created - a.created);
}

export async function saveBook(book) {
  const ok = await run("readwrite", (s) => s.put(book));
  if (!ok) memory.set(book.id, book);
  refreshCount();
}

async function removeBook(id) {
  memory.delete(id);
  await run("readwrite", (s) => s.delete(id));
  refreshCount();
}

export async function refreshCount() {
  const n = (await listBooks()).length;
  const badge = $("#book-count");
  if (badge) { badge.textContent = String(n); badge.hidden = !n; }
}

/** A picture on screen, shrunk to a small JPEG so a whole library fits in the browser's storage. */
export async function keepPicture(url, width = 760) {
  const blob = await (await fetch(url)).blob();
  const bitmap = await createImageBitmap(blob);
  const scale = Math.min(1, width / bitmap.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  return canvas.toDataURL("image/jpeg", 0.82);
}

// ------------------------------------------------------------------------------------------- the reader
const AUDIENCE = { kids: "Little ones", family: "Family", adults: "Grown-ups" };
const PAGE_CHARS = 560; // about one printed page of the book at reading size
const fmtDate = (ms) => new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Turn the story as it was told into pages: a title page, pictures on pages of their own, text in between. */
function paginate(book) {
  const cast = (book.cast || []).map((c) => `<li><span class="bk-emo">${esc(c.emoji || c.name[0])}</span><b>${esc(c.name)}</b>${c.fromWish ? ' <i>· from your wish</i>' : c.role ? ` <i>· ${esc(c.role)}</i>` : ""}</li>`).join("");
  const pages = [`<div class="bk-title"><div class="bk-kicker">StoryWeaver presents</div><h2>${esc(book.title)}</h2>
    <p class="bk-logline">${esc(book.logline || "")}</p><div class="bk-orn">❦</div>
    <p class="bk-meta">${esc(AUDIENCE[book.audience] || "")} · ${book.minutes} min · ${fmtDate(book.created)}${book.finished ? "" : " · unfinished"}</p>
    ${cast ? `<ul class="bk-cast">${cast}</ul>` : ""}</div>`];
  let page = [], size = 0, first = true;
  const flush = () => { if (page.length) pages.push(`<div class="bk-text">${page.join("")}</div>`); page = []; size = 0; };
  for (const item of book.flow || []) {
    if (item.type === "picture") {
      if (!item.src) continue;
      flush();
      pages.push(`<figure class="bk-pic"><img src="${item.src}" alt=""></figure>`);
      continue;
    }
    let html = "";
    if (item.type === "line") {
      const who = item.speaker && item.speaker !== "narrator" ? `<span class="bk-who">${esc(item.name)}</span>` : "";
      html = `<p class="${first ? "bk-first" : ""}${who ? " bk-say" : ""}">${who}${who ? `“${esc(item.text)}”` : esc(item.text)}</p>`;
      first = false;
    } else if (item.type === "choice") {
      html = `<p class="bk-mark">✦ ${item.auto ? "The story chose" : "You chose"}: <b>${esc(item.text)}</b> ✦</p>`;
    } else if (item.type === "wish") {
      html = `<p class="bk-mark wish">✨ Your wish: <b>${esc(item.text)}</b></p>`;
    } else if (item.type === "qa") {
      html = `<p class="bk-mark qa">You asked: “${esc(item.q)}”<br><span>${esc(item.a)}</span></p>`;
    }
    const cost = (item.text || item.a || "").length + 40;
    if (size + cost > PAGE_CHARS) flush();
    page.push(html);
    size += cost;
  }
  flush();
  pages.push(`<div class="bk-end"><div class="bk-orn">❦</div><h3>The End</h3>
    ${book.choices?.length ? `<p>Your choices: ${book.choices.map(esc).join(" → ")}</p>` : ""}
    ${book.wishes?.length ? `<p>Your wishes: ${book.wishes.map(esc).join(" · ")}</p>` : ""}</div>`);
  return pages;
}

export class StorybookUI {
  constructor({ onOpen } = {}) {
    this.onOpen = onOpen || (() => {});
    this.pages = [];
    this.spread = 0;
    this.busy = false;
    $("#sb-back").addEventListener("click", () => this.shelf());
    $("#sb-prev").addEventListener("click", () => this.turn(-1));
    $("#sb-next").addEventListener("click", () => this.turn(1));
    $("#sb-delete").addEventListener("click", async () => {
      if (!this.book || !confirm(`Remove “${this.book.title}” from your Storybook?`)) return;
      await removeBook(this.book.id);
      this.shelf();
    });
    addEventListener("keydown", (e) => {
      if ($("#storybook").hidden || $("#sb-reader").hidden) return;
      if (e.key === "ArrowRight") this.turn(1);
      if (e.key === "ArrowLeft") this.turn(-1);
    });
    addEventListener("resize", () => { if (!$("#sb-reader").hidden) this.render(); });
    refreshCount();
  }

  get perSpread() { return innerWidth < 820 ? 1 : 2; }

  async show(id) {
    this.onOpen();
    $("#storybook").hidden = false;
    document.body.classList.add("modal-open");
    if (id) {
      const book = (await listBooks()).find((b) => b.id === id);
      if (book) return this.read(book);
    }
    return this.shelf();
  }

  async shelf() {
    $("#sb-reader").hidden = true;
    $("#sb-shelf").hidden = false;
    const books = await listBooks();
    $("#sb-books").innerHTML = books.length ? books.map((b) => {
      const cover = b.flow?.find((f) => f.type === "picture" && f.src)?.src;
      return `<button class="sb-cover" data-id="${esc(b.id)}" style="${cover ? `--cover:url('${cover}')` : ""}">
        <span class="sb-spine"></span><span class="sb-art"></span>
        <span class="sb-name">${esc(b.title)}</span>
        <span class="sb-meta">${esc(AUDIENCE[b.audience] || "")} · ${b.minutes} min · ${fmtDate(b.created)}</span>
        ${b.finished ? "" : '<span class="sb-ribbon">unfinished</span>'}</button>`;
    }).join("") : `<div class="sb-empty"><div class="sb-empty-ico">📖</div><b>Your Storybook is waiting for its first story.</b>
        <p>Every story you hear is kept here, with its pictures, so you can read it again.</p></div>`;
    document.querySelectorAll("#sb-books .sb-cover").forEach((el) => el.addEventListener("click", () =>
      this.read(books.find((b) => b.id === el.dataset.id))));
  }

  read(book) {
    this.book = book;
    this.pages = paginate(book);
    this.spread = 0;
    $("#sb-shelf").hidden = true;
    $("#sb-reader").hidden = false;
    $("#sb-title").textContent = book.title;
    this.render();
  }

  page(i) {
    const html = this.pages[i];
    return html === undefined ? '<div class="bk-blank"></div>' : `${html}<span class="bk-no">${i + 1}</span>`;
  }

  render() {
    const per = this.perSpread;
    const last = Math.ceil(this.pages.length / per) - 1;
    this.spread = Math.max(0, Math.min(this.spread, last));
    const first = this.spread * per;
    $("#sb-book").classList.toggle("single", per === 1);
    $("#sb-left").innerHTML = this.page(first);
    $("#sb-right").innerHTML = per === 2 ? this.page(first + 1) : "";
    $("#sb-pageno").textContent = per === 2 ? `${first + 1}–${Math.min(first + 2, this.pages.length)} of ${this.pages.length}`
      : `${first + 1} of ${this.pages.length}`;
    $("#sb-prev").disabled = this.spread === 0;
    $("#sb-next").disabled = this.spread >= last;
  }

  /** Turn a page: a leaf lifts from the right (or left) page and swings over the spine, like a real book. */
  turn(dir) {
    const per = this.perSpread;
    const last = Math.ceil(this.pages.length / per) - 1;
    const next = this.spread + dir;
    if (this.busy || next < 0 || next > last) return;
    if (per === 1 || matchMedia("(prefers-reduced-motion: reduce)").matches) { this.spread = next; this.render(); return; }
    this.busy = true;
    const leaf = $("#sb-leaf");
    const now = this.spread * 2, then = next * 2;
    if (dir > 0) {
      $(".front", leaf).innerHTML = this.page(now + 1);
      $(".back", leaf).innerHTML = this.page(then);
      $("#sb-right").innerHTML = this.page(then + 1);
    } else {
      $(".front", leaf).innerHTML = this.page(now);
      $(".back", leaf).innerHTML = this.page(then + 1);
      $("#sb-left").innerHTML = this.page(then);
    }
    leaf.className = `leaf ${dir > 0 ? "fwd" : "back-turn"}`;
    leaf.addEventListener("animationend", () => {
      leaf.className = "leaf";
      this.spread = next;
      this.render();
      this.busy = false;
    }, { once: true });
  }
}
