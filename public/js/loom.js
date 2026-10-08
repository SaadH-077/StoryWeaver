// The home page's loom: a tapestry is woven, row by row, at the edges of the screen while you dream up a story — a
// glowing shuttle carries the weft over and under the warp threads, and kilim-like motifs appear as the rows build
// up. Only the new stitches are drawn each frame (a few tiny shapes), so it costs next to nothing; it rests whenever
// the home page is not on screen, and is drawn at once, without motion, for people who prefer reduced motion.
const CELL_W = 18;
const CELL_H = 12;
const BANDS = ["#2d2468", "#3b2574", "#472a6f", "#22406a", "#1a4550", "#3a2a66"];
const GOLD = "#ecb963";
const ROSE = "#dc7898";
const TEAL = "#55c7b8";
const WARP = "#d9cdb0";

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

/** The colour of the weft at a cell: banded rows with diamonds and dots (a kilim, roughly). */
function colour(row, col) {
  const r = row % 12, c = col % 12;
  const d = Math.abs(r - 6) + Math.abs(c - 6);
  if (d === 5) return GOLD;
  if (d === 2) return ROSE;
  if (d === 0) return GOLD;
  if (r === 0) return TEAL;
  return BANDS[Math.floor(row / 4) % BANDS.length];
}

export function startLoom(canvas, shuttle) {
  const cx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0, h = 0, dpr = 1, cols = 0, rows = 0, row = 0, col = 0, pause = 0, boost = 0, last = 0;

  // the tapestry shows at the sides of the screen (and faintly along the bottom), leaving the page itself clear
  const alpha = (x, y) => {
    const nx = Math.abs(x - w / 2) / (w / 2), ny = (y - h / 2) / (h / 2);
    const side = w < 700 ? smooth(0.9, 1.0, nx) : smooth(0.6, 0.97, nx);
    return Math.max(side, smooth(0.75, 1.0, ny) * 0.45) * 0.82 * smooth(64, 130, y); // the top bar stays clear
  };

  function stitch(r, c) {
    const x = c * CELL_W, y = r * CELL_H, a = alpha(x + CELL_W / 2, y + CELL_H / 2);
    if (a < 0.03) return false;
    const yarn = colour(r, c);
    if ((r + c) % 2 === 0) { // plain weave: here the weft passes over the warp — a raised stitch with a little sheen
      cx.globalAlpha = a;
      cx.fillStyle = yarn;
      cx.beginPath();
      cx.roundRect(x - 1, y + 1.5, CELL_W + 2, CELL_H - 3, (CELL_H - 3) / 2);
      cx.fill();
      cx.globalAlpha = a * 0.3;
      cx.fillStyle = "#fff";
      cx.fillRect(x + 4, y + 3, CELL_W - 8, 1);
    } else { // here it dips under the warp: the weft in shadow, the warp thread on top
      cx.globalAlpha = a * 0.5;
      cx.fillStyle = yarn;
      cx.fillRect(x, y + 3, CELL_W, CELL_H - 6);
      cx.globalAlpha = a * 0.42;
      cx.fillStyle = WARP;
      cx.beginPath();
      cx.roundRect(x + CELL_W / 2 - 3, y - 1, 6, CELL_H + 2, 3);
      cx.fill();
    }
    return true;
  }

  function warp() { // the bare warp threads, waiting for the weft
    cx.fillStyle = WARP;
    for (let c = 0; c < cols; c++) {
      const x = c * CELL_W + CELL_W / 2;
      for (let y = 0; y < h; y += CELL_H * 2) {
        const a = alpha(x, y) * 0.12;
        if (a < 0.02) continue;
        cx.globalAlpha = a;
        cx.fillRect(x - 0.6, y, 1.2, CELL_H * 2);
      }
    }
  }

  function reset() {
    dpr = Math.min(2, devicePixelRatio || 1);
    w = innerWidth; h = innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    cx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(w / CELL_W); rows = Math.ceil(h / CELL_H);
    row = 0; col = 0; pause = 0;
    canvas.style.opacity = "1";
    warp();
    if (still) { for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) stitch(r, c); row = rows; }
  }

  const active = () => document.body.dataset.view === "home" && !document.body.classList.contains("modal-open") && !document.hidden;

  function frame(t) {
    requestAnimationFrame(frame);
    if (still || !active() || t - last < 33) return; // ~30 fps is plenty
    const dt = Math.min(100, t - last);
    last = t;
    if (row >= rows) { // the tapestry is finished: admire it, let it fade, then weave a new one
      shuttle.style.opacity = "0";
      pause += dt;
      if (pause > 9000 && canvas.style.opacity !== "0") canvas.style.opacity = "0";
      if (pause > 11500) { cx.clearRect(0, 0, w, h); reset(); }
      return;
    }
    const steps = Math.max(1, Math.round((dt / 33) * (boost > t ? 7 : 3)));
    const forward = row % 2 === 0; // the shuttle goes back and forth, like a real one
    for (let drawn = 0; drawn < steps && row < rows;) { // the clear middle takes no time: the shuttle flies across it
      if (stitch(row, forward ? col : cols - 1 - col)) drawn += 1;
      if (++col >= cols) { col = 0; row++; }
    }
    const c = row % 2 === 0 ? col : cols - 1 - col;
    const x = c * CELL_W, y = row * CELL_H + CELL_H / 2;
    shuttle.style.opacity = String(Math.min(1, alpha(x, y) * 1.6));
    shuttle.style.transform = `translate(${x - 14}px, ${y - 4}px) scaleX(${row % 2 === 0 ? 1 : -1})`;
  }

  let resizeTimer = null;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(reset, 200); });
  reset();
  requestAnimationFrame(frame);
  return { boost(ms = 700) { boost = performance.now() + ms; } };
}

/** The thread that runs down the story form: two strands twist through a knot at each step and are drawn in
 *  gold as far as the story is ready — once there is an idea, they run all the way to "Weave my story". */
export function startSpine(form, svg, steps, isReady) {
  const NS = "http://www.w3.org/2000/svg";
  let length = 0;
  const strands = [0, 1].map((k) => {
    const base = document.createElementNS(NS, "path");
    const lit = document.createElementNS(NS, "path");
    base.setAttribute("class", `sp-base s${k}`);
    lit.setAttribute("class", `sp-lit s${k}`);
    svg.append(base, lit);
    return { base, lit };
  });
  const knots = steps.map((_, i) => {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "sp-knot");
    g.innerHTML = `<circle r="11"/><text dy="3.6">${["I", "II", "III", "IV", "V"][i]}</text>`;
    svg.append(g);
    return g;
  });
  let ys = [];

  function layout() {
    const top = form.getBoundingClientRect().top;
    ys = steps.map((el) => el.getBoundingClientRect().top - top + 30);
    const height = form.scrollHeight;
    svg.setAttribute("viewBox", `0 0 40 ${height}`);
    svg.style.height = `${height}px`;
    strands.forEach(({ base, lit }, k) => {
      const sway = k ? -11 : 11;
      let d = `M20 0`;
      let prev = 0;
      for (const y of ys) {
        const g = (y - prev) / 3;
        d += ` C${20 + sway} ${prev + g} ${20 - sway} ${y - g} 20 ${y}`;
        prev = y;
      }
      base.setAttribute("d", d);
      lit.setAttribute("d", d);
    });
    length = strands[0].lit.getTotalLength();
    strands.forEach(({ lit }) => { lit.style.strokeDasharray = `${length}`; });
    knots.forEach((g, i) => g.setAttribute("transform", `translate(20 ${ys[i]})`));
    update(true);
  }

  function update(instant = false) {
    const done = isReady();
    let reach = -1; // how far the thread has been woven: every step before it is ready
    while (done[reach + 1]) reach += 1;
    const target = reach < 0 ? ys[0] * 0.6 : ys[reach];
    const fraction = Math.min(1, target / (ys.at(-1) || 1));
    strands.forEach(({ lit }) => {
      if (instant) lit.style.transition = "none";
      // the dash offset follows path length, which grows a little faster than depth: close enough for a thread
      lit.style.strokeDashoffset = String(length * (1 - fraction));
      if (instant) requestAnimationFrame(() => { lit.style.transition = ""; });
    });
    knots.forEach((g, i) => g.classList.toggle("tied", i <= reach));
    form.classList.toggle("woven", reach === steps.length - 1);
  }

  new ResizeObserver(() => layout()).observe(form);
  layout();
  return { update: () => update(false), layout };
}
