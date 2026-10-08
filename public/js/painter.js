// The last illustrator in the chain: paints a paper-cut storybook scene in the browser, from the chapter's ambience
// and mood. It needs no network, so a story never shows an empty sky — it fills the first seconds while the first
// picture is painted, and stands in for any picture the image models can't deliver (free quotas run out).

const PALETTES = { // sky top, sky horizon, light
  wonder: ["#2a2a6c", "#8a63b0", "#ffd9a0"], adventure: ["#1d4f7c", "#e7a75e", "#ffe2a6"],
  mystery: ["#111a33", "#3b3768", "#a9bcff"], tension: ["#2b1322", "#73303e", "#ffa284"],
  calm: ["#1c3c4e", "#6fa9a5", "#fff2cc"], joy: ["#3f7fd6", "#ffd39e", "#fff6d6"],
  melancholy: ["#1e2433", "#596580", "#cfd8ea"], triumph: ["#3a296a", "#f2a75b", "#ffeaa9"],
};
const NIGHT = new Set(["night", "space", "magic", "cave"]);

function rng(seedText) { // mulberry32 on a string hash: the same scene for the same moment
  let h = 1779033703;
  for (const ch of seedText) h = Math.imul(h ^ ch.charCodeAt(0), 3432918353) >>> 0;
  return () => {
    h = (h + 0x6d2b79f5) >>> 0;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function mix(a, b, f) {
  const p = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * f).toString(16).padStart(2, "0")).join("")}`;
}

const W = 1536, H = 1024;

function hills(r, base, amp, color, waves = 3) {
  const phase = r() * 6.28, freq = (waves * 6.28) / W;
  let d = `M0 ${H} L0 ${base}`;
  for (let x = 0; x <= W; x += 32) {
    const y = base - amp * (0.6 * Math.sin(x * freq + phase) + 0.4 * Math.sin(x * freq * 2.3 + phase * 1.7));
    d += ` L${x} ${y.toFixed(1)}`;
  }
  return `<path d="${d} L${W} ${H} Z" fill="${color}"/>`;
}

function trees(r, base, count, color, scale = 1) {
  let out = "";
  for (let i = 0; i < count; i++) {
    const x = r() * W, h = (90 + r() * 120) * scale, w = h * (0.32 + r() * 0.12), y = base + r() * 40 * scale;
    out += r() < 0.6
      ? `<path d="M${x} ${y - h} L${x + w / 2} ${y - h * 0.35} L${x + w * 0.28} ${y - h * 0.38} L${x + w * 0.62} ${y} L${x - w * 0.62} ${y} L${x - w * 0.28} ${y - h * 0.38} L${x - w / 2} ${y - h * 0.35} Z" fill="${color}"/>`
      : `<circle cx="${x}" cy="${y - h * 0.62}" r="${w * 0.75}" fill="${color}"/><rect x="${x - 5 * scale}" y="${y - h * 0.4}" width="${10 * scale}" height="${h * 0.4}" fill="${color}"/>`;
  }
  return out;
}

function skyline(r, base, color, lit) {
  let out = "", x = -20;
  while (x < W) {
    const w = 60 + r() * 110, h = 120 + r() * 260;
    out += `<rect x="${x.toFixed(0)}" y="${(base - h).toFixed(0)}" width="${w.toFixed(0)}" height="${(h + 400).toFixed(0)}" fill="${color}"/>`;
    for (let wy = base - h + 18; wy < base - 12; wy += 26) {
      for (let wx = x + 10; wx < x + w - 14; wx += 22) if (r() < 0.32) out += `<rect x="${wx.toFixed(0)}" y="${wy.toFixed(0)}" width="9" height="12" fill="${lit}" opacity="${(0.45 + r() * 0.5).toFixed(2)}"/>`;
    }
    x += w + 6 + r() * 18;
  }
  return out;
}

function waves(r, base, color, line) {
  let out = `<rect x="0" y="${base}" width="${W}" height="${H - base}" fill="${color}"/>`;
  for (let row = 0; row < 7; row++) {
    const y = base + 22 + row * row * 9 + row * 14;
    let d = "";
    for (let x = -40; x < W; x += 80 + r() * 60) d += `M${x.toFixed(0)} ${y} q 20 -9 40 0 `;
    out += `<path d="${d}" stroke="${line}" stroke-width="${2 + row * 0.6}" fill="none" opacity="${(0.35 - row * 0.03).toFixed(2)}" stroke-linecap="round"/>`;
  }
  return out;
}

/** An SVG data URL: sky, light, three layers of land shaped by the ambience, and a soft vignette. */
export function paintScene({ ambience = [], mood = "wonder", seed = "story" } = {}) {
  const r = rng(`${seed}|${ambience.join(",")}|${mood}`);
  const [top, horizon, light] = PALETTES[mood] || PALETTES.wonder;
  const has = (a) => ambience.includes(a);
  const night = ambience.some((a) => NIGHT.has(a)) || ["mystery", "melancholy"].includes(mood);
  const skyTop = night ? mix(top, "#05040c", 0.35) : top;
  const skyLow = night ? mix(horizon, "#0b0a1a", 0.45) : horizon;
  const ink = (f) => mix(skyLow, "#07060f", f);
  const cx = W * (0.25 + r() * 0.5), cy = H * (night ? 0.24 : 0.5) + r() * 60;
  let art = "";

  // light: moon by night, a low warm sun by day
  art += `<circle cx="${cx}" cy="${cy}" r="${night ? 170 : 260}" fill="url(#halo)"/>`;
  art += night ? `<circle cx="${cx}" cy="${cy}" r="54" fill="${mix(light, "#ffffff", 0.5)}"/><circle cx="${cx + 18}" cy="${cy - 10}" r="48" fill="${skyTop}" opacity=".28"/>`
    : `<circle cx="${cx}" cy="${cy}" r="70" fill="${light}" opacity=".95"/>`;
  if (night || has("magic")) {
    for (let i = 0; i < 90; i++) art += `<circle cx="${(r() * W).toFixed(0)}" cy="${(r() * H * 0.55).toFixed(0)}" r="${(0.8 + r() * 1.8).toFixed(1)}" fill="#fff6e0" opacity="${(0.25 + r() * 0.6).toFixed(2)}"/>`;
  }
  if (has("magic")) {
    art += `<path d="M0 ${H * 0.32} C ${W * 0.3} ${H * 0.18}, ${W * 0.6} ${H * 0.42}, ${W} ${H * 0.22}" stroke="#9cf5e6" stroke-width="60" fill="none" opacity=".12"/>`;
  }
  if (has("storm") || has("rain")) {
    for (let i = 0; i < 9; i++) {
      const x = r() * W, y = 80 + r() * 200;
      art += `<ellipse cx="${x}" cy="${y}" rx="${160 + r() * 140}" ry="${44 + r() * 30}" fill="${mix(skyTop, "#1a1a26", 0.5)}" opacity=".75"/>`;
    }
    if (has("storm")) art += `<path d="M${cx + 120} 160 l-40 120 h40 l-60 150" stroke="#fff3c4" stroke-width="7" fill="none" opacity=".8"/>`;
  }

  // land
  if (has("space")) {
    art += `<circle cx="${W * 0.78}" cy="${H * 0.36}" r="120" fill="${mix(light, horizon, 0.4)}"/><ellipse cx="${W * 0.78}" cy="${H * 0.36}" rx="210" ry="40" stroke="${light}" stroke-width="10" fill="none" opacity=".6"/>`;
    art += hills(r, H * 0.86, 40, ink(0.55), 1);
  } else if (has("underwater")) {
    for (let i = 0; i < 6; i++) art += `<path d="M${W * (0.1 + i * 0.16)} 0 L${W * (0.16 + i * 0.16)} 0 L${W * (0.3 + i * 0.12)} ${H} L${W * (0.18 + i * 0.12)} ${H} Z" fill="#bff3ff" opacity=".05"/>`;
    for (let i = 0; i < 26; i++) {
      const x = r() * W, h = 120 + r() * 260;
      art += `<path d="M${x} ${H} q ${-30 + r() * 60} ${-h / 2} ${-10 + r() * 20} ${-h}" stroke="${ink(0.35 + r() * 0.3)}" stroke-width="${6 + r() * 8}" fill="none" stroke-linecap="round"/>`;
    }
    art += hills(r, H * 0.9, 30, ink(0.6), 2);
  } else if (has("cave")) {
    art += hills(r, H * 0.78, 50, ink(0.45), 2);
    art += `<path d="M0 0 H${W} V${H} H${W * 0.86} C ${W * 0.84} ${H * 0.3}, ${W * 0.16} ${H * 0.3}, ${W * 0.14} ${H} H0 Z" fill="${ink(0.82)}"/>`;
    for (let i = 0; i < 14; i++) {
      const x = W * 0.15 + r() * W * 0.7;
      art += `<path d="M${x - 18} ${H * 0.2 + r() * 40} l18 ${60 + r() * 90} l18 ${-60 - r() * 90} Z" fill="${ink(0.82)}"/>`;
    }
  } else if (has("city") || has("machine")) {
    art += hills(r, H * 0.7, 30, ink(0.3), 2);
    art += skyline(r, H * 0.78, ink(0.5), light);
    art += `<rect x="0" y="${H * 0.86}" width="${W}" height="${H * 0.14}" fill="${ink(0.72)}"/>`;
  } else if (has("ocean") || has("river")) {
    art += hills(r, H * 0.6, 60, ink(0.32), 2);
    art += waves(r, H * 0.66, mix(skyLow, "#0d2a44", 0.45), light);
    if (has("river")) art += hills(r, H * 0.94, 30, ink(0.7), 3);
  } else {
    art += hills(r, H * 0.62, 70, ink(0.3), 2);
    if (has("forest")) art += trees(r, H * 0.64, 22, ink(0.42), 0.8);
    art += hills(r, H * 0.74, 55, ink(0.5), 3);
    if (has("forest")) art += trees(r, H * 0.8, 12, ink(0.66), 1.3);
    art += hills(r, H * 0.88, 40, ink(0.68), 4);
    if (has("wind")) for (let i = 0; i < 70; i++) {
      const x = r() * W;
      art += `<path d="M${x} ${H} q 6 -30 ${18 + r() * 14} ${-54 - r() * 40}" stroke="${ink(0.75)}" stroke-width="4" fill="none"/>`;
    }
  }
  if (has("fire")) art += `<circle cx="${W / 2}" cy="${H * 0.9}" r="200" fill="url(#ember)"/><path d="M${W / 2 - 34} ${H * 0.93} q 34 -110 34 -150 q 30 70 34 150 Z" fill="#ffb347" opacity=".9"/>`;

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${skyTop}"/><stop offset="1" stop-color="${skyLow}"/></linearGradient>
<radialGradient id="halo"><stop offset="0" stop-color="${light}" stop-opacity=".55"/><stop offset="1" stop-color="${light}" stop-opacity="0"/></radialGradient>
<radialGradient id="ember"><stop offset="0" stop-color="#ffb347" stop-opacity=".6"/><stop offset="1" stop-color="#ff6b2b" stop-opacity="0"/></radialGradient>
<radialGradient id="vig" cx=".5" cy=".45" r=".75"><stop offset=".6" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient></defs>
<rect width="${W}" height="${H}" fill="url(#sky)"/>${art}<rect width="${W}" height="${H}" fill="url(#vig)"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
