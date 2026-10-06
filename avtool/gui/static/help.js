/* AVTool — guided tour, Help Center and keyboard shortcuts. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const app = () => window.AVTool;  // set by app.js: { api, toast, getState, showTab }

  // ------------------------------------------------------------- tour
  const STEPS = [
    { target: null, title: "Welcome aboard, Sebastian",
      text: "AVTool turns your videos into <b>transcripts and subtitles</b>, right here on your Mac. Nothing is uploaded. This one-minute tour shows you around." },
    { target: ".toolbar", title: "Add your videos",
      text: "Click <b>＋ FILES</b> or <b>＋ FOLDER</b>, paste a path, or simply <b>drag videos and folders from Finder</b> onto the window." },
    { target: ".rack", title: "The queue rack",
      text: "Each file gets a row with its length, progress bar and status light. Row buttons: <b>▤</b> read the transcript, <b>⌕</b> show in Finder, <b>✕</b> remove from the list (nothing is deleted)." },
    { target: ".transport-buttons", title: "Start and stop",
      text: "<b>START</b> works through the queue one file at a time. <b>STOP</b> is always safe: it cleans up, and START picks up where it left off." },
    { target: ".transport", title: "Watch it work",
      text: "The meter, the <b>EXTRACT › TRANSCRIBE › WRITE</b> lights and <b>TIME LEFT</b> update live. The counters tally done, skipped and failed." },
    { target: ".knob-row", tab: "settings", title: "Quality, language, captions",
      text: "Turn the <b>QUALITY</b> knob: BEST for final work, DRAFT for quick checks. Keep language on <b>EN</b> for English. <b>STANDARD</b> captions suit Premiere and CapCut; <b>REELS</b> are short one-liners for vertical video." },
    { target: ".switches", tab: "settings", title: "Handy switches",
      text: "<b>Boost quiet voices</b> helps catch audience questions. <b>Redo finished files</b> re-transcribes videos already done. <b>Keep Mac awake</b> guards long batches." },
    { target: ".tabs", title: "Glossary, Viewer, Log",
      text: "<b>GLOSSARY</b>: names to spell right (Evan, Smooth Scaling…). <b>VIEWER</b>: read, search and copy finished transcripts. <b>LOG</b>: the play-by-play." },
    { target: ".readouts", title: "Status lights",
      text: "<b>ENGINE</b> shows the transcriber (MLX · Apple GPU on your Mac). <b>MODEL</b> lights blue once it's downloaded. <b>LOCAL ONLY</b>: nothing leaves this Mac." },
    { target: "#btn-help", title: "Help is always here",
      text: "Open the <b>Help Center</b> for every control explained, Premiere and CapCut guides, tips and FAQs. You can replay this tour from there. Shortcut: <b>?</b>" },
  ];
  let step = 0;
  let touring = false;

  function startTour() {
    closeHelp();
    touring = true;
    step = 0;
    $("#tour").hidden = false;
    $("#tour-dots").innerHTML = STEPS.map(() => "<i></i>").join("");
    showStep();
  }

  function endTour() {
    if (!touring) return;
    touring = false;
    $("#tour").hidden = true;
    const a = app();
    if (a) a.api("/api/settings", { tour_done: true }).catch(() => {});
  }

  function showStep() {
    const s = STEPS[step];
    if (s.tab && app()) app().showTab(s.tab);
    const card = $("#tour-card"), spot = $("#tour-spot");
    const welcome = !s.target;
    card.classList.toggle("welcome", welcome);
    $("#tour-step").textContent = welcome ? "QUICK TOUR · 1 MINUTE" : `STEP ${step} / ${STEPS.length - 1}`;
    $("#tour-title").textContent = s.title;
    $("#tour-text").innerHTML = (welcome ? '<span class="mark tour-logo"></span>' : "") + s.text;
    $$("#tour-dots i").forEach((d, i) => d.classList.toggle("on", i === step));
    $("#tour-back").disabled = step === 0;
    $("#tour-next").textContent = step === STEPS.length - 1 ? "LET'S GO" : (welcome ? "SHOW ME" : "NEXT");
    $("#tour-skip").hidden = step === STEPS.length - 1;

    if (welcome) {
      spot.className = "tour-spot center";
      spot.style.left = innerWidth / 2 + "px";
      spot.style.top = innerHeight / 2 + "px";
      requestAnimationFrame(() => place(card, null));
      return;
    }
    const el = $(s.target);
    const r = el.getBoundingClientRect();
    const pad = 8;
    spot.className = "tour-spot";
    Object.assign(spot.style, {
      left: r.left - pad + "px", top: r.top - pad + "px",
      width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px",
    });
    requestAnimationFrame(() => place(card, r));
    $("#tour-next").focus();
  }

  function place(card, r) {
    const cw = card.offsetWidth, ch = card.offsetHeight, gap = 18, m = 14;
    let left, top;
    if (!r) {
      left = (innerWidth - cw) / 2;
      top = (innerHeight - ch) / 2;
    } else if (innerHeight - r.bottom > ch + gap + m) {         // below
      left = r.left + r.width / 2 - cw / 2; top = r.bottom + gap;
    } else if (r.top > ch + gap + m) {                            // above
      left = r.left + r.width / 2 - cw / 2; top = r.top - ch - gap;
    } else if (r.left > cw + gap + m) {                           // left
      left = r.left - cw - gap; top = r.top + r.height / 2 - ch / 2;
    } else {                                                      // right
      left = r.right + gap; top = r.top + r.height / 2 - ch / 2;
    }
    card.style.left = Math.max(m, Math.min(left, innerWidth - cw - m)) + "px";
    card.style.top = Math.max(m, Math.min(top, innerHeight - ch - m)) + "px";
  }

  function next() { if (step < STEPS.length - 1) { step++; showStep(); } else endTour(); }
  function back() { if (step > 0) { step--; showStep(); } }

  // ------------------------------------------------------------- help center
  function openHelp(sectionTitle) {
    if (touring) return;
    $("#help").hidden = false;
    $("#help-search").value = "";
    filterHelp("");
    if (sectionTitle) goTo(sectionTitle);
    $("#help-search").focus();
  }
  function closeHelp() { $("#help").hidden = true; }

  function buildNav() {
    const nav = $("#help-links");
    $$("#help-body section").forEach((sec) => {
      const a = document.createElement("a");
      a.textContent = sec.dataset.title;
      a.addEventListener("click", () => goTo(sec.dataset.title));
      nav.appendChild(a);
    });
  }
  function goTo(title) {
    const sec = $$("#help-body section").find((s) => s.dataset.title === title);
    if (sec) sec.scrollIntoView({ block: "start" });
    markActive(title);
  }
  function markActive(title) {
    $$("#help-links a").forEach((a) => a.classList.toggle("on", a.textContent === title));
  }
  function onScroll() {
    const body = $("#help-body");
    const top = body.getBoundingClientRect().top + 40;
    let current = null;
    $$("#help-body section:not(.hidden)").forEach((s) => { if (s.getBoundingClientRect().top <= top) current = s; });
    current = current || $("#help-body section:not(.hidden)");
    if (current) markActive(current.dataset.title);
  }
  function filterHelp(q) {
    q = q.trim().toLowerCase();
    let shown = 0;
    $$("#help-body section").forEach((sec, i) => {
      const hit = !q || sec.textContent.toLowerCase().includes(q);
      sec.classList.toggle("hidden", !hit);
      $$("#help-links a")[i].hidden = !hit;
      if (hit) shown++;
      // Open matching FAQ answers so the hit is visible.
      $$("details", sec).forEach((d) => { d.open = !!q && d.textContent.toLowerCase().includes(q); });
    });
    let empty = $("#help-empty");
    if (!shown) {
      if (!empty) {
        empty = document.createElement("p");
        empty.id = "help-empty";
        empty.className = "note";
        $("#help-body").appendChild(empty);
      }
      empty.textContent = `Nothing matches “${q}”. Try a simpler word, like “captions”, “glossary” or “Premiere”.`;
    } else if (empty) empty.remove();
    $("#help-body").scrollTop = 0;
    onScroll();
  }

  // ------------------------------------------------------------- keyboard
  function typing(e) {
    const t = e.target;
    return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  }
  document.addEventListener("keydown", (e) => {
    if (touring) {
      if (e.key === "Escape") { e.preventDefault(); endTour(); }
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
      return;
    }
    if (!$("#help").hidden) {
      if (e.key === "Escape") { e.preventDefault(); closeHelp(); }
      return;
    }
    const cmd = e.metaKey || e.ctrlKey;
    if (cmd && e.key.toLowerCase() === "o") { e.preventDefault(); $(e.shiftKey ? "#btn-add-folder" : "#btn-add-files").click(); }
    else if (cmd && e.key === "Enter") { e.preventDefault(); if (!$("#btn-start").disabled) $("#btn-start").click(); }
    else if (cmd && e.key === ".") { e.preventDefault(); if (!$("#btn-stop").disabled) $("#btn-stop").click(); }
    else if (e.key === "?" && !typing(e)) { e.preventDefault(); openHelp(); }
  });

  // ------------------------------------------------------------- wiring
  $("#btn-help").addEventListener("click", () => openHelp());
  $("#help-close").addEventListener("click", closeHelp);
  $("#help").addEventListener("click", (e) => { if (e.target.id === "help") closeHelp(); });
  $("#help-search").addEventListener("input", (e) => filterHelp(e.target.value));
  $("#help-body").addEventListener("scroll", onScroll);
  $("#btn-replay-tour").addEventListener("click", () => { closeHelp(); startTour(); });
  $("#tour-next").addEventListener("click", next);
  $("#tour-back").addEventListener("click", back);
  $("#tour-skip").addEventListener("click", endTour);
  window.addEventListener("resize", () => { if (touring) showStep(); });
  buildNav();

  // First launch: the tour runs once (remembered in the app's settings).
  document.addEventListener("avtool:first-state", (e) => {
    const s = e.detail;
    if (s && s.settings && !s.settings.tour_done && !s.running) setTimeout(startTour, 700);
  });
  window.AVToolHelp = { startTour, openHelp };
})();
