/* AVTool — living starfield behind the whole app.
   Three depths of stars drifting slowly, gentle twinkle, a rare shooting star.
   Light on the computer: ~30 frames a second, pauses when the window is hidden,
   and stays still if the Mac's "Reduce motion" setting is on. */
(() => {
  "use strict";
  const canvas = document.getElementById("stars");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const LAYERS = [
    { count: 320, size: [0.4, 0.85], speed: 0.6, alpha: [0.3, 0.6] },   // far
    { count: 130, size: [0.75, 1.3], speed: 1.4, alpha: [0.5, 0.85] },  // middle
    { count: 40, size: [1.25, 2.0], speed: 2.6, alpha: [0.75, 1.0] },   // near
  ];
  const TINTS = ["255,255,255", "214,232,255", "170,214,255", "120,200,255", "205,190,255"];
  let stars = [], w = 0, h = 0, dpr = 1, shooting = null, nextShot = 0, last = 0;

  const rand = (a, b) => a + Math.random() * (b - a);

  function resize() {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = rect.width; h = rect.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const area = (w * h) / (1320 * 860);  // density stays the same at any window size
    stars = [];
    LAYERS.forEach((layer, depth) => {
      for (let i = 0; i < Math.round(layer.count * area); i++) {
        stars.push({
          x: Math.random() * w, y: Math.random() * h, depth,
          r: rand(...layer.size), a: rand(...layer.alpha),
          tw: rand(0.4, 1.6), ph: Math.random() * Math.PI * 2,
          tint: TINTS[Math.floor(Math.random() * TINTS.length)],
          v: layer.speed,
        });
      }
    });
    if (still) draw(0);
  }

  function launchShootingStar(t) {
    const fromLeft = Math.random() < 0.5;
    shooting = {
      x: fromLeft ? rand(-40, w * 0.4) : rand(w * 0.6, w + 40), y: rand(-20, h * 0.35),
      vx: (fromLeft ? 1 : -1) * rand(520, 760), vy: rand(170, 260),
      life: 0, max: rand(0.7, 1.1),
    };
    nextShot = t + rand(9, 22);
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      const twinkle = still ? 1 : 0.65 + 0.35 * Math.sin(t * s.tw + s.ph);
      ctx.globalAlpha = s.a * twinkle;
      ctx.fillStyle = `rgb(${s.tint})`;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
      if (s.depth === 2 && s.r > 1.5) {  // brightest stars get a soft cross glint
        ctx.globalAlpha = s.a * twinkle * 0.35;
        ctx.fillRect(s.x - s.r * 3, s.y - 0.4, s.r * 6, 0.8);
        ctx.fillRect(s.x - 0.4, s.y - s.r * 3, 0.8, s.r * 6);
      }
    }
    if (shooting) {
      const k = shooting.life / shooting.max;
      const fade = k < 0.15 ? k / 0.15 : 1 - (k - 0.15) / 0.85;
      const tail = 0.12;
      const grad = ctx.createLinearGradient(shooting.x, shooting.y,
        shooting.x - shooting.vx * tail, shooting.y - shooting.vy * tail);
      grad.addColorStop(0, `rgba(220,240,255,${0.9 * fade})`);
      grad.addColorStop(1, "rgba(79,216,255,0)");
      ctx.globalAlpha = 1;
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(shooting.x, shooting.y);
      ctx.lineTo(shooting.x - shooting.vx * tail, shooting.y - shooting.vy * tail);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  function step(now) {
    requestAnimationFrame(step);
    if (document.hidden || now - last < 33) return;  // ~30 fps is plenty for drifting stars
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    const t = now / 1000;
    for (const s of stars) {  // slow drift down and to the left, nearer stars faster
      s.x -= s.v * dt * 2.2;
      s.y += s.v * dt * 0.9;
      if (s.x < -2) s.x += w + 4;
      if (s.y > h + 2) s.y -= h + 4;
    }
    if (shooting) {
      shooting.life += dt;
      shooting.x += shooting.vx * dt;
      shooting.y += shooting.vy * dt;
      if (shooting.life > shooting.max) shooting = null;
    } else if (t > nextShot) {
      if (nextShot) launchShootingStar(t);
      else nextShot = t + rand(4, 9);
    }
    draw(t);
  }

  window.addEventListener("resize", resize);
  resize();
  if (!still) requestAnimationFrame(step);
})();
