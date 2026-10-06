/* AVTool — Sebastian Success · V1.0
   The page polls the local engine for state and sends button presses back.
   Everything goes to 127.0.0.1 (this Mac) with a per-launch secret key. */
(() => {
  "use strict";

  const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || "";
  const MODELS = ["small", "medium", "large-v3-turbo"];
  const MODEL_NAMES = { "small": "SMALL · FAST DRAFT", "medium": "MEDIUM", "large-v3-turbo": "LARGE-V3-TURBO" };
  const STAGE_START = { extract: 0, transcribe: 0.08, write: 0.98 };
  const STAGE_SIZE = { extract: 0.08, transcribe: 0.90, write: 0.02 };
  const STAGE_SHORT = { extract: "EXTRACT", transcribe: "TRANSCRIBE", write: "WRITING" };
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  let state = null;
  let logSeq = 0;
  let selectedId = null;
  let viewer = { id: null, data: null };
  let glossaryDirty = false;
  let pollTimer = null;

  // ------------------------------------------------------------- API
  async function api(path, body) {
    const opts = { headers: { "X-AVTool-Token": TOKEN } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  function toast(text, bad = false) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.textContent = text;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), bad ? 6000 : 3200);
  }

  const guard = (fn) => async (...args) => {
    try { await fn(...args); } catch (err) { toast(err.message, true); }
  };

  // ------------------------------------------------------------- formatting
  function hms(sec) {
    if (sec == null || !isFinite(sec)) return "--:--:--";
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
  }
  function stamp(sec) {
    sec = Math.floor(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : String(m)) + ":" + String(s).padStart(2, "0");
  }
  function human(sec) {
    if (!sec) return "0m";
    const m = Math.round(sec / 60);
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
  }
  function withinFile(item) {
    if (item.status === "done") return 1;
    if (item.status !== "running") return 0;
    return (STAGE_START[item.stage] || 0) + (STAGE_SIZE[item.stage] || 0) * item.fraction;
  }

  // ------------------------------------------------------------- polling
  async function poll() {
    clearTimeout(pollTimer);
    try {
      const s = await api(`/api/state?since=${logSeq}`);
      render(s);
    } catch (err) {
      $("#now-text").textContent = "ENGINE NOT RESPONDING — RESTART THE APP";
    }
    pollTimer = setTimeout(poll, state && state.running ? 500 : 1500);
  }

  // ------------------------------------------------------------- render
  function render(s) {
    const prev = state;
    state = s;
    $("#ver").textContent = (s.version || "1.0").split(".").slice(0, 2).join(".");
    renderHeader(s);
    renderRows(s);
    renderTransport(s);
    renderSettings(s, prev);
    renderLog(s);
    renderViewerOptions(s);
    if (prev && prev.running && !s.running) onBatchEnd(s);
    if (!prev) document.dispatchEvent(new CustomEvent("avtool:first-state", { detail: s }));
  }

  function renderHeader(s) {
    const e = s.engine || {};
    const led = $("#led-engine");
    if (!e.checked) {
      $("#engine-label").textContent = "CHECKING…";
      led.className = "led pulse on";
    } else if (e.error || !e.ffmpeg) {
      $("#engine-label").textContent = e.ffmpeg ? "NOT INSTALLED" : "FFMPEG MISSING";
      led.className = "led bad";
    } else {
      $("#engine-label").textContent = e.label || e.backend.toUpperCase();
      led.className = "led on";
    }
    $("#model-label").textContent = (s.settings.model || "").toUpperCase();
    $("#led-model").className = "led " + (e.checked ? (e.model_ready ? "on" : "warn") : "");
    $("#led-model").parentElement.title = e.model_ready ? "Model downloaded — works offline"
      : "Model not downloaded yet: it downloads once on first Start (needs internet)";
  }

  const STATUS = {
    probing: ["CHECKING…", ""], ready: ["READY", ""], queued: ["QUEUED", ""],
    running: ["", "run"], done: ["DONE", "ok"], stopped: ["STOPPED", "warn"],
    skipped: ["SKIPPED", "warn"], failed: ["FAILED", "bad"],
  };

  function renderRows(s) {
    const box = $("#rows");
    const seen = new Set();
    s.items.forEach((item, idx) => {
      seen.add(item.id);
      let row = box.querySelector(`[data-id="${item.id}"]`);
      if (!row) {
        row = document.createElement("div");
        row.className = "row";
        row.dataset.id = item.id;
        row.setAttribute("role", "listitem");
        row.innerHTML = `
          <span class="num"></span><i class="led"></i>
          <span class="name"><b></b><small></small></span>
          <span class="dur"></span>
          <span class="mini"><i></i></span>
          <span class="status"></span>
          <span class="acts">
            <button class="icon-btn" data-act="view" title="View transcript" aria-label="View transcript">▤</button>
            <button class="icon-btn" data-act="reveal" title="Show in Finder" aria-label="Show in Finder">⌕</button>
            <button class="icon-btn" data-act="remove" title="Remove from queue" aria-label="Remove">✕</button>
          </span>`;
        box.appendChild(row);
      }
      if (box.children[idx] !== row) box.insertBefore(row, box.children[idx]);
      row.className = "row " + item.status + (item.id === selectedId ? " selected" : "");
      row.querySelector(".num").textContent = String(idx + 1).padStart(2, "0");
      row.querySelector(".name b").textContent = item.name;
      row.querySelector(".name b").title = item.path;
      // LRM marks keep the slashes in order while the long path is trimmed from the left.
      row.querySelector(".name small").textContent = "\u200E" + item.folder + "/\u200E";
      row.querySelector(".dur").textContent = item.duration_text || "";
      row.querySelector(".mini > i").style.width = (withinFile(item) * 100).toFixed(1) + "%";
      const [label, cls] = STATUS[item.status] || [item.status.toUpperCase(), ""];
      const st = row.querySelector(".status");
      st.className = "status " + cls;
      if (item.status === "running") {
        st.textContent = `${STAGE_SHORT[item.stage] || "WORKING"} ${Math.round(item.fraction * 100)}%`;
      } else if (item.status === "done" && item.note === "no speech detected") {
        st.textContent = "DONE · NO SPEECH";
      } else if (item.status === "skipped" && /no audio|empty/i.test(item.note)) {
        st.textContent = "NO AUDIO";
      } else {
        st.textContent = label;
      }
      st.title = item.note || "";
      const led = row.querySelector(".led");
      led.className = "led " + ({ running: "on pulse", done: "ok", failed: "bad", skipped: "warn",
        stopped: "warn", ready: "on", queued: "on" }[item.status] || "");
      row.querySelector('[data-act="view"]').disabled = item.status !== "done";
      row.querySelector('[data-act="remove"]').disabled = item.status === "running" || item.status === "queued";
    });
    $$(".row", box).forEach((row) => { if (!seen.has(row.dataset.id)) row.remove(); });
    const audio = s.items.reduce((a, i) => a + (i.duration || 0), 0);
    $("#queue-meta").textContent = `${s.items.length} FILE${s.items.length === 1 ? "" : "S"} · ${human(audio)} AUDIO`;
  }

  function renderTransport(s) {
    const start = $("#btn-start"), stop = $("#btn-stop");
    start.disabled = s.running;
    start.classList.toggle("busy", s.running);
    stop.disabled = !s.running || s.stopping;
    const items = s.items;
    const running = items.find((i) => i.status === "running");
    const count = (st) => items.filter((i) => i.status === st).length;
    $("#c-done").textContent = count("done");
    $("#c-skip").textContent = count("skipped");
    $("#c-fail").textContent = count("failed");

    let fraction = 0, now;
    if (s.running) {
      fraction = s.batch.fraction || 0;
      if (s.stopping) now = "STOPPING — CLEANING UP THE CURRENT FILE…";
      else if (running) {
        const n = s.batch.total ? ` · FILE ${s.batch.index}/${s.batch.total}` : "";
        now = `${running.name}${n}`;
      } else if (s.loading) now = "LOADING THE MODEL INTO MEMORY…";
      else now = "PREPARING…";
    } else {
      const ready = items.filter((i) => ["ready", "stopped"].includes(i.status));
      if (s.last_run) {
        const c = s.last_run.counts || {};
        fraction = s.last_run.interrupted ? 0 : 1;
        now = s.last_run.interrupted ? "STOPPED — PRESS START TO CONTINUE WHERE IT LEFT OFF"
          : `FINISHED · ${c.done || 0} DONE · ${c["done-before"] || 0} ALREADY DONE · ${c.skipped || 0} SKIPPED · ${c.failed || 0} FAILED`;
        if (ready.length && !s.last_run.interrupted) now = `READY — ${ready.length} FILE${ready.length === 1 ? "" : "S"} QUEUED`;
      } else if (ready.length) {
        now = `READY — ${ready.length} FILE${ready.length === 1 ? "" : "S"} · ${human(s.queued_audio)} OF AUDIO · PRESS START`;
      } else if (items.length) {
        now = items.some((i) => i.status === "probing") ? "CHECKING FILES…" : "NOTHING NEW TO TRANSCRIBE";
      } else {
        now = "IDLE — ADD FILES TO BEGIN";
      }
    }
    $("#now-text").textContent = now;
    $("#lcd-pct").textContent = String(Math.round(fraction * 100)).padStart(3, "0") + "%";
    $("#lcd-eta").textContent = s.running ? (s.batch.eta != null ? hms(s.batch.eta) : "CALC…") : "--:--:--";

    const meter = $("#meter");
    if (!meter.children.length) for (let i = 0; i < 48; i++) meter.appendChild(document.createElement("i"));
    const lit = Math.round(fraction * 48);
    [...meter.children].forEach((seg, i) => {
      seg.className = i < lit ? (i === lit - 1 && s.running ? "on peak" : "on") : "";
    });
    const order = ["extract", "transcribe", "write"];
    const cur = running ? order.indexOf(running.stage) : -1;
    $$(".stages [data-stage]").forEach((el) => {
      const i = order.indexOf(el.dataset.stage);
      el.className = i === cur ? "on" : (cur > i ? "done" : "");
    });
  }

  function setSeg(seg, value) {
    $$("button", seg).forEach((b) => b.classList.toggle("on", b.dataset.value === value));
  }

  function renderSettings(s, prev) {
    const st = s.settings;
    $(".side").classList.toggle("locked", s.running);
    $("#lock-note").hidden = !s.running;
    $$(".seg[data-setting]").forEach((seg) => setSeg(seg, st[seg.dataset.setting]));
    $$("input[data-setting]").forEach((cb) => { cb.checked = !!st[cb.dataset.setting]; });
    setKnob(Math.max(0, MODELS.indexOf(st.model)));
    setSeg($("#out-mode"), st.out ? "custom" : (outCustomPending ? "custom" : "next"));
    $("#out-path").hidden = !(st.out || outCustomPending);
    $("#out-path-text").textContent = st.out || "Choose a folder…";
    $$("#formats button[data-fmt]").forEach((b) => b.classList.toggle("on", st.formats.includes(b.dataset.fmt)));
    if (!prev) loadGlossary();
  }

  function renderLog(s) {
    if (!s.log.length) return;
    const con = $("#console");
    const atBottom = con.scrollTop + con.clientHeight >= con.scrollHeight - 30;
    for (const line of s.log) {
      const span = document.createElement("span");
      const t = line.text;
      if (/✓/.test(t)) span.className = "ok";
      else if (/✗|FAILED/.test(t)) span.className = "bad";
      else if (/⚠|■|Skipped/.test(t)) span.className = "warn";
      span.textContent = t + "\n";
      con.appendChild(span);
    }
    while (con.childNodes.length > 1500) con.removeChild(con.firstChild);
    logSeq = s.log_seq;
    if (atBottom) con.scrollTop = con.scrollHeight;
  }

  // ------------------------------------------------------------- knob
  const KNOB_ANGLES = [-120, 0, 120];
  function arcPath(a0, a1) {
    const r = 56, c = 60, rad = (a) => (a - 90) * Math.PI / 180;
    const p = (a) => [c + r * Math.cos(rad(a)), c + r * Math.sin(rad(a))];
    const [x0, y0] = p(a0), [x1, y1] = p(a1);
    const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  function setKnob(v) {
    const angle = KNOB_ANGLES[v];
    $("#knob-pointer").style.transform = `rotate(${angle}deg)`;
    $("#knob-arc").setAttribute("d", arcPath(-135, Math.max(angle, -134)));
    $("#knob-model").setAttribute("aria-valuenow", v);
    $("#knob-model").setAttribute("aria-valuetext", MODELS[v]);
    $$(".knob-labels span").forEach((s) => s.classList.toggle("on", Number(s.dataset.v) === v));
    $("#knob-value").textContent = MODEL_NAMES[MODELS[v]];
  }
  function knobValue() { return Math.max(0, MODELS.indexOf(state ? state.settings.model : "large-v3-turbo")); }
  const setModel = guard(async (v) => {
    v = Math.min(2, Math.max(0, v));
    if (v === knobValue()) return;
    setKnob(v);
    state.settings = await api("/api/settings", { model: MODELS[v] });
    toast(v === 2 ? "Best quality (large-v3-turbo)" : v === 1 ? "Balanced (medium) — faster" : "Draft (small) — fastest, rougher");
  });

  // ------------------------------------------------------------- settings events
  let outCustomPending = false;
  const saveSetting = guard(async (changes) => {
    state.settings = await api("/api/settings", changes);
    renderSettings(state, state);
  });

  function bindSettings() {
    $$(".seg[data-setting]").forEach((seg) => seg.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (b) saveSetting({ [seg.dataset.setting]: b.dataset.value });
    }));
    $$("input[data-setting]").forEach((cb) => cb.addEventListener("change", () => saveSetting({ [cb.dataset.setting]: cb.checked })));
    $("#formats").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-fmt]");
      if (!b || b.disabled) return;
      const set = new Set(state.settings.formats);
      set.has(b.dataset.fmt) ? set.delete(b.dataset.fmt) : set.add(b.dataset.fmt);
      saveSetting({ formats: [...set] });
    });
    $("#out-mode").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.value === "next") { outCustomPending = false; saveSetting({ out: "" }); }
      else { outCustomPending = true; renderSettings(state, state); if (!state.settings.out) chooseOutDir(); }
    });
    $("#btn-outdir").addEventListener("click", () => chooseOutDir());

    const knob = $("#knob-model");
    let dragY = null, startV = 0;
    knob.addEventListener("pointerdown", (e) => { dragY = e.clientY; startV = knobValue(); knob.setPointerCapture(e.pointerId); });
    knob.addEventListener("pointermove", (e) => {
      if (dragY == null) return;
      const steps = Math.round((dragY - e.clientY) / 28);
      setKnob(Math.min(2, Math.max(0, startV + steps)));
    });
    knob.addEventListener("pointerup", (e) => {
      if (dragY == null) return;
      const moved = Math.abs(dragY - e.clientY) > 4;
      const steps = Math.round((dragY - e.clientY) / 28);
      dragY = null;
      setModel(moved ? startV + steps : (startV + 1) % 3);
    });
    knob.addEventListener("keydown", (e) => {
      if (["ArrowUp", "ArrowRight"].includes(e.key)) { e.preventDefault(); setModel(knobValue() + 1); }
      if (["ArrowDown", "ArrowLeft"].includes(e.key)) { e.preventDefault(); setModel(knobValue() - 1); }
    });
    $$(".knob-labels span").forEach((s) => s.addEventListener("click", () => setModel(Number(s.dataset.v))));
  }

  const chooseOutDir = guard(async () => {
    const r = await api("/api/choose", { kind: "outdir" });
    if (r.settings) state.settings = r.settings;
    if (!r.paths || !r.paths.length) { if (!state.settings.out) outCustomPending = false; }
    else toast("Transcripts will be saved to " + r.paths[0]);
    renderSettings(state, state);
  });

  // ------------------------------------------------------------- queue events
  const addPaths = guard(async (paths) => {
    const r = await api("/api/add", { paths });
    if (r.added) toast(`Added ${r.added} file${r.added === 1 ? "" : "s"}`);
    (r.problems || []).forEach((p) => toast(p, true));
    poll();
  });

  function bindQueue() {
    $("#btn-add-files").addEventListener("click", guard(async () => {
      const r = await api("/api/choose", { kind: "files" });
      if (r.added) toast(`Added ${r.added} file${r.added === 1 ? "" : "s"}`);
      poll();
    }));
    $("#btn-add-folder").addEventListener("click", guard(async () => {
      const r = await api("/api/choose", { kind: "folder" });
      if (r.paths && r.paths.length && !r.added) toast((r.problems && r.problems[0]) || "No new media files in that folder", true);
      else if (r.added) toast(`Added ${r.added} file${r.added === 1 ? "" : "s"}`);
      poll();
    }));
    $("#path-form").addEventListener("submit", (e) => {
      e.preventDefault();
      let p = $("#path-input").value.trim().replace(/^['"]|['"]$/g, "").replace(/\\(.)/g, "$1");
      if (!p) return;
      $("#path-input").value = "";
      addPaths([p]);
    });
    $("#btn-clear").addEventListener("click", guard(async () => { await api("/api/clear", { which: "finished" }); poll(); }));
    $("#rows").addEventListener("click", guard(async (e) => {
      const row = e.target.closest(".row");
      if (!row) return;
      const item = state.items.find((i) => i.id === row.dataset.id);
      const act = e.target.closest("[data-act]");
      if (!act) { selectedId = item.id; renderRows(state); if (item.status === "done") openViewer(item.id, false); return; }
      if (act.dataset.act === "remove") { await api("/api/remove", { id: item.id }); poll(); }
      if (act.dataset.act === "reveal") await api("/api/reveal", { path: item.path });
      if (act.dataset.act === "view") openViewer(item.id, true);
    }));

    $("#btn-start").addEventListener("click", guard(async () => {
      const r = await api("/api/start", {});
      if (!r.ok) toast(r.error, true);
      else toast(`Starting ${r.count} file${r.count === 1 ? "" : "s"} — this Mac stays awake`);
      poll();
    }));
    $("#btn-stop").addEventListener("click", guard(async () => { await api("/api/stop", {}); poll(); }));

    // Drag and drop. In the Mac app the window passes real file paths to the
    // engine directly; a plain browser can't, so it suggests the buttons.
    let depth = 0;
    const isFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    window.addEventListener("dragenter", (e) => { if (!isFiles(e)) return; e.preventDefault(); depth++; document.body.classList.add("dragging"); });
    window.addEventListener("dragover", (e) => { if (isFiles(e)) e.preventDefault(); });
    window.addEventListener("dragleave", () => { depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove("dragging"); });
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      depth = 0;
      document.body.classList.remove("dragging");
      if (!window.pywebview) toast("Drag-and-drop works in the AVTool app. Here, use ＋ FILES / ＋ FOLDER.", true);
      setTimeout(poll, 400);
      setTimeout(poll, 1200);
    });
  }

  function onBatchEnd(s) {
    const r = s.last_run || {};
    const c = r.counts || {};
    if (r.interrupted) toast("Stopped. Press START to continue where it left off.");
    else toast(`Batch finished: ${c.done || 0} done, ${c.skipped || 0} skipped, ${c.failed || 0} failed`, (c.failed || 0) > 0);
    if (viewer.id) loadViewer();
  }

  // ------------------------------------------------------------- tabs
  function showTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $$(".tabpane").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
    if (name === "log") { const c = $("#console"); c.scrollTop = c.scrollHeight; }
  }

  // ------------------------------------------------------------- glossary
  function countTerms(text) {
    const terms = new Set();
    text.split("\n").forEach((raw) => {
      const line = raw.split("#")[0].trim();
      if (!line) return;
      terms.add(line.includes("->") ? line.split("->")[1].trim() : line);
    });
    terms.delete("");
    return terms.size;
  }
  function updateGlossaryCount() {
    const n = countTerms($("#glossary-text").value);
    $("#glossary-count").textContent = `${n} TERM${n === 1 ? "" : "S"}` + (n > 40 ? " · TOO MANY — TRIM IT" : "") + (glossaryDirty ? " · UNSAVED" : "");
    $("#glossary-count").style.color = n > 40 ? "var(--warn)" : "";
  }
  const loadGlossary = guard(async () => {
    const g = await api("/api/glossary");
    if (!glossaryDirty) $("#glossary-text").value = g.text;
    updateGlossaryCount();
  });
  function bindGlossary() {
    $("#glossary-text").addEventListener("input", () => { glossaryDirty = true; updateGlossaryCount(); });
    $("#btn-glossary-save").addEventListener("click", guard(async () => {
      const r = await api("/api/glossary", { text: $("#glossary-text").value });
      glossaryDirty = false;
      updateGlossaryCount();
      toast(`Glossary saved · ${r.terms.length} terms` + (r.truncated ? " (trimmed: keep it short)" : ""));
    }));
  }

  // ------------------------------------------------------------- viewer
  function renderViewerOptions(s) {
    const sel = $("#viewer-select");
    const done = s.items.filter((i) => i.status === "done");
    const key = done.map((i) => i.id).join(",");
    if (sel.dataset.key === key) return;
    sel.dataset.key = key;
    sel.innerHTML = "";
    if (!done.length) {
      const o = document.createElement("option");
      o.textContent = "No finished transcripts yet";
      o.value = "";
      sel.appendChild(o);
      return;
    }
    done.forEach((i) => {
      const o = document.createElement("option");
      o.value = i.id;
      o.textContent = i.name;
      sel.appendChild(o);
    });
    if (viewer.id && done.some((i) => i.id === viewer.id)) sel.value = viewer.id;
  }

  function openViewer(id, switchTab) {
    viewer.id = id;
    $("#viewer-select").value = id;
    if (switchTab) showTab("viewer");
    loadViewer();
  }

  const loadViewer = guard(async () => {
    if (!viewer.id) return;
    viewer.data = await api(`/api/transcript?id=${encodeURIComponent(viewer.id)}`);
    renderViewer();
  });

  function renderViewer() {
    const d = viewer.data;
    const box = $("#viewer-lines");
    box.innerHTML = "";
    if (!d) return;
    const q = $("#viewer-search").value.trim().toLowerCase();
    $("#viewer-meta").textContent = `${(d.language || "?").toUpperCase()} · ${d.model || ""} · ${d.segments.length} LINES`;
    if (!d.segments.length) {
      box.innerHTML = '<div class="empty">No speech detected in this file.</div>';
      return;
    }
    let shown = 0;
    d.segments.forEach((seg) => {
      if (q && !seg.text.toLowerCase().includes(q)) return;
      shown++;
      const line = document.createElement("div");
      line.className = "vline";
      line.title = "Click to copy";
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = stamp(seg.start);
      const txt = document.createElement("span");
      if (q) {
        const i = seg.text.toLowerCase().indexOf(q);
        txt.append(seg.text.slice(0, i));
        const m = document.createElement("mark");
        m.textContent = seg.text.slice(i, i + q.length);
        txt.append(m, seg.text.slice(i + q.length));
      } else txt.textContent = seg.text;
      line.append(t, txt);
      line.addEventListener("click", () => copy(`[${stamp(seg.start)}] ${seg.text}`, "Line copied"));
      box.appendChild(line);
    });
    if (!shown) box.innerHTML = '<div class="empty">No lines match your search.</div>';
    $$(".viewer-actions [data-open]").forEach((b) => { b.disabled = !d.files[b.dataset.open]; });
  }

  async function copy(text, msg) {
    try { await navigator.clipboard.writeText(text); }
    catch (_) {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); ta.remove();
    }
    toast(msg);
  }

  function bindViewer() {
    $("#viewer-select").addEventListener("change", (e) => { if (e.target.value) openViewer(e.target.value, false); });
    $("#viewer-search").addEventListener("input", renderViewer);
    $$(".viewer-actions [data-open]").forEach((b) => b.addEventListener("click", guard(async () => {
      if (viewer.data && viewer.data.files[b.dataset.open]) await api("/api/open", { path: viewer.data.files[b.dataset.open] });
    })));
    $("#btn-copy-all").addEventListener("click", () => {
      if (!viewer.data) return;
      copy(viewer.data.segments.map((s) => s.text).join("\n"), "Transcript copied");
    });
    $("#btn-reveal").addEventListener("click", guard(async () => {
      const f = viewer.data && (viewer.data.files.txt || viewer.data.files.json);
      if (f) await api("/api/reveal", { path: f });
    }));
  }

  // ------------------------------------------------------------- boot
  // Shared with help.js (tour, Help Center, shortcuts).
  window.AVTool = { api, toast, getState: () => state, showTab };

  function boot() {
    $$(".tab").forEach((t) => t.addEventListener("click", () => {
      showTab(t.dataset.tab);
      if (t.dataset.tab === "glossary") loadGlossary();
      if (t.dataset.tab === "viewer" && !viewer.id) {
        const v = $("#viewer-select").value;
        if (v) openViewer(v, false);
      }
    }));
    bindSettings();
    bindQueue();
    bindGlossary();
    bindViewer();
    setKnob(2);
    if (!TOKEN) $("#now-text").textContent = "OPEN THIS PAGE FROM THE AVTOOL APP";
    poll();
  }
  boot();
})();
