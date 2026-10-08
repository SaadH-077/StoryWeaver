// A quiet, twinkling starfield behind the interface (paused when the tab is hidden).
export function startStars(canvas) {
  const cx = canvas.getContext("2d");
  let stars = [];
  const resize = () => {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = innerWidth * dpr;
    canvas.height = innerHeight * dpr;
    const count = Math.round((innerWidth * innerHeight) / 9000);
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * canvas.width, y: Math.random() * canvas.height,
      r: (Math.random() * 1.1 + 0.25) * dpr, p: Math.random() * Math.PI * 2, s: 0.004 + Math.random() * 0.012,
    }));
  };
  resize();
  addEventListener("resize", resize);
  let last = 0;
  const frame = (t) => {
    if (t - last > 50 && !document.hidden) { // ~20 fps is plenty for twinkling
      last = t;
      cx.clearRect(0, 0, canvas.width, canvas.height);
      for (const s of stars) {
        s.p += s.s;
        cx.globalAlpha = 0.25 + 0.6 * (0.5 + 0.5 * Math.sin(s.p));
        cx.fillStyle = "#fff8ec";
        cx.beginPath();
        cx.arc(s.x, s.y, s.r, 0, 6.283);
        cx.fill();
      }
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}
