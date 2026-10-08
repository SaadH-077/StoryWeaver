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

/** Threads that flow in from both sides of the screen, gather into a bundle and run through the StoryWeaver
 *  wordmark — as if the name is being woven from them — with a few bright beads (shuttles) travelling along them.
 *  About twenty curves at ~30 fps on an unscaled canvas; it rests when the wordmark is out of sight. */
export function startThreads(canvas, mark) {
  const cx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const COLORS = ["247,200,115", "255,143,179", "161,132,255", "98,227,210", "130,200,255", "255,224,163"];
  const N = 20;
  const threads = Array.from({ length: N }, (_, i) => ({
    color: COLORS[i % COLORS.length], phase: i * 1.7, speed: 0.18 + (i % 5) * 0.05, width: 0.9 + (i % 4) * 0.45,
    alpha: 0.16 + (i % 3) * 0.08,
  }));
  const beads = Array.from({ length: 6 }, (_, i) => ({ thread: (i * 7) % N, s: i / 6, v: 0.0022 + (i % 3) * 0.0008 }));
  let w = 0, h = 0, last = 0, t = 0;

  const resize = () => { w = canvas.width = innerWidth; h = canvas.height = innerHeight; };
  addEventListener("resize", resize);
  resize();

  // each thread: in from the left at one height, through the bundle in the word, out to the right at a mirrored height
  function geometry(th, i, r) {
    const mid = r.top + r.height * 0.56, half = r.width * 0.5;
    const spread = r.height * 0.7;
    const k = i / (N - 1);
    const yl = h * (0.04 + 0.92 * k) + Math.sin(t * th.speed + th.phase) * 26;
    const yr = h * (0.04 + 0.92 * k) + Math.cos(t * th.speed * 0.9 + th.phase) * 26;
    const yc = mid + (k - 0.5) * spread + Math.sin(t * 0.5 + th.phase) * 4;
    const a = r.left + half * 0.12, b = r.right - half * 0.12;
    return [[-30, yl], [a * 0.42, yl], [a * 0.72, yc], [a, yc],
      [b, yc], [b + (w - b) * 0.28, yc], [b + (w - b) * 0.58, yr], [w + 30, yr]];
  }

  const bez = (p0, p1, p2, p3, u) => {
    const v = 1 - u;
    return [v * v * v * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u * u * u * p3[0],
      v * v * v * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u * u * u * p3[1]];
  };
  function pointAt(g, s) { // 0-0.4 the left curve, 0.4-0.6 through the word, 0.6-1 the right curve
    if (s < 0.4) return bez(g[0], g[1], g[2], g[3], s / 0.4);
    if (s < 0.6) { const u = (s - 0.4) / 0.2; return [g[3][0] + (g[4][0] - g[3][0]) * u, g[3][1] + (g[4][1] - g[3][1]) * u]; }
    return bez(g[4], g[5], g[6], g[7], (s - 0.6) / 0.4);
  }

  function draw() {
    const r = mark.getBoundingClientRect();
    cx.clearRect(0, 0, w, h);
    if (!r.width) return false;
    const geos = threads.map((th, i) => geometry(th, i, r));
    threads.forEach((th, i) => {
      const g = geos[i];
      const grad = cx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, `rgba(${th.color},0)`);
      grad.addColorStop(0.3, `rgba(${th.color},${th.alpha})`);
      grad.addColorStop(0.5, `rgba(${th.color},${th.alpha * 0.2})`); // quieter behind the letters
      grad.addColorStop(0.7, `rgba(${th.color},${th.alpha})`);
      grad.addColorStop(1, `rgba(${th.color},0)`);
      cx.strokeStyle = grad;
      cx.lineWidth = th.width;
      cx.beginPath();
      cx.moveTo(...g[0]);
      cx.bezierCurveTo(...g[1], ...g[2], ...g[3]);
      cx.lineTo(...g[4]);
      cx.bezierCurveTo(...g[5], ...g[6], ...g[7]);
      cx.stroke();
    });
    for (const b of beads) {
      if (!still) b.s = (b.s + b.v) % 1;
      const [x, y] = pointAt(geos[b.thread], b.s);
      const fade = Math.sin(Math.PI * b.s); // bright mid-way, gone at the edges
      const glow = cx.createRadialGradient(x, y, 0, x, y, 9);
      glow.addColorStop(0, `rgba(255,244,214,${0.85 * fade})`);
      glow.addColorStop(1, "rgba(255,244,214,0)");
      cx.fillStyle = glow;
      cx.beginPath();
      cx.arc(x, y, 9, 0, 6.283);
      cx.fill();
    }
    return r.bottom > -80;
  }

  const active = () => document.body.dataset.view === "home" && !document.body.classList.contains("modal-open") && !document.hidden;
  function frame(now) {
    requestAnimationFrame(frame);
    if (!active() || now - last < 33) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (!still) t += dt;
    const r = mark.getBoundingClientRect();
    if (r.bottom < -80 && canvas.dataset.idle) return; // scrolled past the wordmark: rest
    canvas.dataset.idle = draw() ? "" : "1";
  }
  requestAnimationFrame(frame);
}
