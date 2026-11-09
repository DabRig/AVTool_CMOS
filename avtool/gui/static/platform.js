/* AV Transcriber — speak the computer's language.
   On Windows: Finder → File Explorer, ⌘ → Ctrl, "Mac" → "PC", and Help blocks
   marked data-os="mac" / data-os="win" show only on the matching system.
   Runs before the other scripts so nothing flashes in the wrong wording. */
(() => {
  "use strict";
  const params = new URLSearchParams(location.hash.slice(1));
  const forced = params.get("os");  // "#…&os=win" lets the look be checked on any computer
  const isWin = forced ? forced === "win" : /Windows/i.test(navigator.userAgent);
  document.documentElement.classList.add(isWin ? "os-win" : "os-mac");

  const WIN = [
    ["MLX · Apple GPU on your Mac", "CUDA · NVIDIA GPU on your PC"],
    ["⌘+ / ⌘− / ⌘0", "Ctrl + / − / 0"],
    ["SHOW IN FINDER", "SHOW IN EXPLORER"],
    ["Show in Finder", "Show in File Explorer"],
    ["from Finder", "from File Explorer"],
    ["in Finder", "in File Explorer"],
    ["Finder picker", "file picker"],
    ["Finder", "File Explorer"],
    ["Keep Mac awake", "Keep PC awake"],
    ["this Mac", "this PC"],
    ["your Mac", "your PC"],
    ["the Mac", "the PC"],
    ["Mac's", "PC's"],
    ["⌘", "Ctrl"],
    ["⇧", "Shift"],
    ["↩", "Enter"],
  ];

  function t(text) {
    if (!isWin || !text) return text;
    for (const [mac, win] of WIN) text = text.split(mac).join(win);
    return text;
  }

  function localize(root) {
    if (!isWin) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const n of nodes) {
      const next = t(n.nodeValue);
      if (next !== n.nodeValue) n.nodeValue = next;
    }
    for (const el of root.querySelectorAll("[title], [placeholder], [aria-label]")) {
      for (const attr of ["title", "placeholder", "aria-label"]) {
        const v = el.getAttribute(attr);
        if (v) el.setAttribute(attr, t(v));
      }
    }
  }

  window.AVLocale = { isWin, t, localize };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => localize(document.body));
  } else {
    localize(document.body);
  }
})();
