// demo-reel's on-page cursor for web recordings (Screen Studio-like): a large pointer that glides
// to where the real (CDP-driven) mouse goes, and a ripple on each press. It never takes events.
(() => {
  if (window.__reelCursor) return;
  window.__reelCursor = true;
  const SIZE = 34;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${SIZE}" height="${SIZE * 1.4}" viewBox="0 0 20 28">
    <path d="M2 2 L2 22 L7.2 17.2 L10.6 25.4 L14 24 L10.6 16 L17.6 16 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  const install = () => {
    if (document.getElementById("reel-cursor")) return;
    const style = document.createElement("style");
    style.textContent = `
      #reel-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;
        transform:translate(-200px,-200px);transition:transform .45s cubic-bezier(.22,.8,.26,1);
        filter:drop-shadow(0 3px 6px rgba(0,0,0,.35))}
      .reel-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;
        border-radius:50%;border:3px solid rgba(80,140,255,.9);background:rgba(80,140,255,.25);
        animation:reel-ripple .55s ease-out forwards}
      @keyframes reel-ripple{to{transform:scale(4.2);opacity:0}}`;
    document.documentElement.appendChild(style);
    const c = document.createElement("div");
    c.id = "reel-cursor";
    c.innerHTML = svg;
    document.documentElement.appendChild(c);
  };
  const move = (x, y) => {
    install();
    document.getElementById("reel-cursor").style.transform = `translate(${x - 3}px, ${y - 3}px)`;
  };
  addEventListener("mousemove", e => move(e.clientX, e.clientY), true);
  addEventListener("mousedown", e => {
    move(e.clientX, e.clientY);
    const r = document.createElement("div");
    r.className = "reel-ripple";
    r.style.left = e.clientX + "px";
    r.style.top = e.clientY + "px";
    document.documentElement.appendChild(r);
    setTimeout(() => r.remove(), 700);
  }, true);
  // Typing into a field without a click (agent-browser `type <selector>`) still moves the cursor there.
  addEventListener("focusin", e => {
    const b = e.target.getBoundingClientRect && e.target.getBoundingClientRect();
    if (b && b.width) move(b.left + Math.min(b.width * 0.15, 60), b.top + b.height / 2);
  }, true);
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", install); else install();
})();
