/* VisionServe front end.
 *
 * Plain JavaScript, no build step. It talks to the same public API as any other
 * client (X-API-Key header, JSON responses) and reads two extra things the API
 * already exposes: the Server-Timing response header (per-stage timings of a
 * request) and /metrics (Prometheus counters for the System tab).
 */
"use strict";

// ---------- small helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

const esc = (str) => String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { value == null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* private mode */ } },
};

function fmtMs(ms) {
  if (ms == null || Number.isNaN(ms)) return "–";
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  if (ms < 10000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}
function fmtBytes(n) {
  return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}
function timeAgo(iso) {
  const sec = (Date.now() - new Date(iso).getTime()) / 1000;
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

const ICON = {
  ok: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm3.3 5.2-3.8 4.1a.8.8 0 0 1-1.1 0L4.7 8.6a.8.8 0 1 1 1.1-1.1l1.1 1.1 3.2-3.5a.8.8 0 0 1 1.2 1.1z"/></svg>',
  bad: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm2.8 8.7a.8.8 0 1 1-1.1 1.1L8 9.1l-1.7 1.7a.8.8 0 1 1-1.1-1.1L6.9 8 5.2 6.3a.8.8 0 1 1 1.1-1.1L8 6.9l1.7-1.7a.8.8 0 1 1 1.1 1.1L9.1 8z"/></svg>',
  wait: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm.8 7.3V4.5a.8.8 0 0 0-1.6 0V8.6c0 .2.1.4.2.6l2 2a.8.8 0 1 0 1.1-1.1z"/></svg>',
  bolt: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 1 3 9h4l-1 6 6.5-8h-4z"/></svg>',
};
function iconEl(name) { const t = document.createElement("template"); t.innerHTML = ICON[name]; return t.content.firstChild; }

function toast(msg, ms = 3500) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), ms);
}

const tip = {
  el: null,
  show(evt, html) {
    this.el ??= $("#tooltip");
    this.el.innerHTML = html;
    this.el.hidden = false;
    this.move(evt);
  },
  move(evt) {
    if (!this.el || this.el.hidden) return;
    const pad = 14, r = this.el.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    this.el.style.left = `${Math.max(8, x)}px`;
    this.el.style.top = `${Math.max(8, y)}px`;
  },
  hide() { if (this.el) this.el.hidden = true; },
};
function hoverTip(node, htmlFn) {
  node.addEventListener("pointerenter", (e) => tip.show(e, htmlFn()));
  node.addEventListener("pointermove", (e) => tip.move(e));
  node.addEventListener("pointerleave", () => tip.hide());
}

// ---------- API client ----------
const auth = {
  get key() { return store.get("vs.key"); },
  set key(v) { store.set("vs.key", v); },
  get email() { return store.get("vs.email"); },
  set email(v) { store.set("vs.email", v); },
};

/** Call the API. Returns {ok, status, data, headers, ms}; never throws on HTTP errors. */
async function api(path, { method = "GET", body, headers = {}, useKey = true } = {}) {
  const h2 = { ...headers };
  if (useKey && auth.key) h2["X-API-Key"] = auth.key;
  if (body && !(body instanceof FormData)) {
    h2["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const t0 = performance.now();
  let res;
  try {
    res = await fetch(path, { method, headers: h2, body });
  } catch {
    return { ok: false, status: 0, data: { error: { code: "network", message: "API unreachable. Is the server running?" } }, headers: new Headers(), ms: 0 };
  }
  const text = await res.text();
  const ms = performance.now() - t0;
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { ok: res.ok, status: res.status, data, headers: res.headers, ms };
}
const errMsg = (r) => r.data?.error?.message ?? `HTTP ${r.status}`;

/** Parse `name;dur=12.3;desc="x", ...` into {name: {dur, desc}}. */
function parseServerTiming(header) {
  const out = {};
  if (!header) return out;
  for (const part of header.split(",")) {
    const [name, ...params] = part.trim().split(";");
    const entry = {};
    for (const p of params) {
      const [k, v] = p.split("=");
      if (k.trim() === "dur") entry.dur = parseFloat(v);
      if (k.trim() === "desc") entry.desc = v?.replace(/"/g, "");
    }
    out[name.trim()] = entry;
  }
  return out;
}

const STAGES = [
  { key: "decode", label: "Decode", desc: "Check the real file format, decode pixels, SHA-256 of the bytes" },
  { key: "cache", label: "Cache lookup", desc: "Redis GET on infer:{task}:{model version}:{sha256}" },
  { key: "store", label: "Store image", desc: "Upload to S3 storage (first time only) + Postgres images row" },
  { key: "queue", label: "Batch queue", desc: "Waiting in the queue: up to 10 ms for companions, plus any time the GPU is busy with earlier batches" },
  { key: "gpu", label: "GPU", desc: "One Florence-2 forward pass for the whole batch" },
  { key: "save", label: "Save", desc: "Cache write + inference_requests row in Postgres" },
];
const stageColor = (key) => `var(--stage-${key})`;

// ---------- theme ----------
(function initTheme() {
  const saved = store.get("vs.theme");
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme
      ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("vs.theme", next);
  });
})();

// ---------- health pills ----------
let lastReady = null;
async function pollHealth() {
  const r = await api("/readyz", { useKey: false });
  lastReady = r;
  const box = $("#health");
  box.replaceChildren();
  if (r.status === 0) {
    box.append(h("span", { class: "pill bad" }, iconEl("bad"), "API offline"));
  } else {
    const checks = r.data?.checks ?? {};
    const names = { model: "Model", postgres: "Postgres", redis: "Redis" };
    for (const [k, label] of Object.entries(names)) {
      const ok = checks[k];
      const state = ok ? "ok" : k === "model" ? "wait" : "bad";
      const text = ok ? label : k === "model" ? "Model loading" : `${label} down`;
      box.append(h("span", { class: `pill ${state}`, title: `${label}: ${ok ? "ready" : "not ready"}` }, iconEl(state), text));
    }
  }
  if (activeTab === "system") renderReady();
}
setInterval(pollHealth, 5000);

// ---------- account ----------
function showApp() {
  const hasKey = !!auth.key;
  $("#account").hidden = hasKey;
  $("#app").hidden = !hasKey;
  const chip = $("#account-chip");
  chip.hidden = !hasKey;
  if (!hasKey) return;
  const prefix = auth.key.split("_").slice(0, 2).join("_");
  chip.replaceChildren(
    auth.email ? h("span", {}, auth.email) : null,
    h("code", { title: "Your API key prefix (the rest is secret)" }, `${prefix}_…`),
    h("button", { class: "btn small ghost", onclick: rotateKey, title: "Revoke this key and get a new one" }, "Rotate key"),
    h("button", { class: "btn small ghost", onclick: signOut }, "Sign out"),
  );
}

function revealKey(key) {
  $("#key-reveal-value").textContent = key;
  $("#key-reveal").hidden = false;
}
$("#key-copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#key-reveal-value").textContent); toast("Key copied"); }
  catch { toast("Copy failed. Select the key and copy it manually."); }
});
$("#key-dismiss").addEventListener("click", () => ($("#key-reveal").hidden = true));

$("#signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target, btn = $("button", form), err = $(".form-error", form);
  err.textContent = "";
  btn.classList.add("busy");
  const admin = form.admin.value.trim();
  const r = await api("/v1/users", {
    method: "POST", useKey: false,
    body: { email: form.email.value.trim() },
    headers: admin ? { "X-Admin-Token": admin } : {},
  });
  btn.classList.remove("busy");
  if (!r.ok) { err.textContent = r.status === 401 ? "Admin token missing or wrong." : errMsg(r); return; }
  auth.key = r.data.api_key;
  auth.email = r.data.email;
  revealKey(r.data.api_key);
  showApp();
});

$("#key-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target, err = $(".form-error", form), key = form.key.value.trim();
  err.textContent = "";
  const r = await api("/v1/stats/me", { headers: { "X-API-Key": key }, useKey: false });
  if (!r.ok) { err.textContent = r.status === 401 ? "That key is invalid or revoked." : errMsg(r); return; }
  auth.key = key;
  auth.email = null;
  showApp();
});

async function rotateKey() {
  if (!confirm("Revoke the current key and issue a new one? Other clients using the old key will start getting 401.")) return;
  const r = await api("/v1/keys/rotate", { method: "POST" });
  if (!r.ok) { toast(errMsg(r)); return; }
  auth.key = r.data.api_key;
  revealKey(r.data.api_key);
  showApp();
  toast("Old key revoked. Requests with it now return 401.");
}
function signOut() {
  if (!confirm("Forget the key in this browser? Copy it first if you want to come back to this account.")) return;
  auth.key = null;
  auth.email = null;
  $("#key-reveal").hidden = true;
  showApp();
}

// ---------- tabs ----------
let activeTab = "analyze";
for (const tab of $$("[role=tab]")) {
  tab.addEventListener("click", () => {
    activeTab = tab.dataset.tab;
    for (const t of $$("[role=tab]")) t.setAttribute("aria-selected", t === tab);
    for (const p of $$(".tab-panel")) p.hidden = p.dataset.panel !== activeTab;
    store.set("vs.tab", activeTab);
    if (activeTab === "history") loadHistory(true);
    if (activeTab === "system") { renderSystem(); renderReady(); }
  });
}

// ---------- analyze ----------
let currentFile = null;
let selectedTask = "caption";

function setFile(file) {
  if (!file) return;
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
    toast(`${file.type || "That file"} isn't supported here. Use JPEG, PNG or WebP. (The server checks the real bytes too.)`);
  }
  currentFile = file;
  const url = URL.createObjectURL(file);
  const img = $("#preview");
  img.onload = () => {
    $("#file-meta").textContent = `${file.name || "pasted image"} · ${img.naturalWidth}×${img.naturalHeight} · ${fmtBytes(file.size)}`;
  };
  img.src = url;
  img.hidden = false;
  $("#dropzone-empty").hidden = true;
  $("#run-btn").disabled = false;
  $("#burst-source").textContent = "Uses your image from Analyze.";
}

$("#file-input").addEventListener("change", (e) => setFile(e.target.files[0]));
const dz = $("#dropzone");
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); setFile(e.dataTransfer.files[0]); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items ?? [])].find((i) => i.type.startsWith("image/"));
  if (item) { setFile(item.getAsFile()); toast("Image pasted"); }
});

for (const btn of $$(".task-picker [role=radio]")) {
  btn.addEventListener("click", () => {
    selectedTask = btn.dataset.task;
    for (const b of $$(".task-picker [role=radio]")) b.setAttribute("aria-checked", b === btn);
  });
}

async function infer(task, blob, filename = "image.jpg") {
  const form = new FormData();
  form.append("file", blob, filename);
  const r = await api(`/v1/infer/${task}`, { method: "POST", body: form });
  r.timing = parseServerTiming(r.headers.get("Server-Timing"));
  r.requestId = r.headers.get("X-Request-ID");
  return r;
}

$("#run-btn").addEventListener("click", async () => {
  if (!currentFile) return;
  const btn = $("#run-btn");
  btn.classList.add("busy");
  btn.disabled = true;
  const tasks = selectedTask === "all" ? ["caption", "detailed_caption", "ocr"] : [selectedTask];
  // "All three" goes out concurrently; the batcher groups by task, so each task
  // still gets its own GPU pass.
  const results = await Promise.all(tasks.map((t) => infer(t, currentFile, currentFile.name || "image.png")));
  btn.classList.remove("busy");
  btn.disabled = false;
  const box = $("#results");
  box.replaceChildren(...results.map((r, i) => resultCard(tasks[i], r)));
});

const TASK_LABEL = { caption: "Caption", detailed_caption: "Detailed caption", ocr: "Text in the image" };

function resultCard(task, r) {
  if (!r.ok) {
    const e = r.data?.error ?? {};
    const extra = r.status === 429 ? ` Retry after ${r.headers.get("Retry-After")} s.` : "";
    return h("div", { class: "card result-card" },
      h("div", { class: "result-head" },
        h("span", { class: "result-task" }, TASK_LABEL[task]),
        h("span", { class: "badge err" }, iconEl("bad"), `${r.status} ${e.code ?? ""}`)),
      h("p", {}, (e.message ?? "Request failed") + extra),
      e.request_id ? h("p", { class: "hint" }, `request_id ${e.request_id}. Search the server logs for it.`) : null);
  }
  const d = r.data;
  const text = d.result.text || "(no text found)";
  const badges = h("div", { class: "badges" },
    d.cache_hit
      ? h("span", { class: "badge hit", title: "Answer came from Redis; the GPU was skipped" }, iconEl("bolt"), "Cache hit")
      : h("span", { class: "badge", title: "Ran on the GPU" }, "GPU"),
    d.batch_size ? h("span", { class: "badge", title: "How many images shared this GPU forward pass" }, `batch of ${d.batch_size}`) : null,
    h("span", { class: "badge", title: "Server time from validated upload to response" }, `${d.latency_ms} ms server`),
    h("span", { class: "badge", title: "Row id in inference_requests" }, `#${d.request_id}`));

  return h("div", { class: "card result-card" },
    h("div", { class: "result-head" }, h("span", { class: "result-task" }, TASK_LABEL[task]), badges),
    h("p", { class: `result-text ${task === "ocr" ? "ocr" : ""}` }, text),
    traceView(r),
    rawView(r));
}

function traceView(r) {
  const d = r.data, t = r.timing;
  const total = r.ms;
  const measured = STAGES.reduce((acc, st) => acc + (t[st.key]?.dur ?? 0), 0);
  const other = Math.max(0, total - measured);

  const bar = h("div", { class: "stack-bar", role: "img", "aria-label": "Time per stage" });
  const segs = [...STAGES.filter((st) => t[st.key]).map((st) => ({ ...st, ms: t[st.key].dur, color: stageColor(st.key) })),
    { key: "other", label: "Auth, rate limit, HTTP", desc: "API-key check, Redis token bucket, upload transfer, response", ms: other, color: "var(--text-3)" }];
  for (const seg of segs) {
    const div = h("div", { style: `flex:${Math.max(seg.ms, total * 0.004)};background:${seg.color}` });
    hoverTip(div, () => `<b>${esc(seg.label)}</b> ${fmtMs(seg.ms)}<br>${esc(seg.desc)}`);
    bar.append(div);
  }

  const list = h("div", { class: "stage-list" });
  for (const st of STAGES) {
    const v = t[st.key];
    const row = h("div", { class: `stage ${v ? "" : "skipped"}`, title: st.desc },
      h("i", { style: `background:${stageColor(st.key)}` }), h("span", {}, st.label), h("span", {}, v ? fmtMs(v.dur) : "skipped"));
    list.append(row);
  }
  list.append(h("div", { class: "stage", title: "Not inside the route handler: auth + rate limit dependencies, HTTP transfer" },
    h("i", { style: "background:var(--text-3)" }), h("span", {}, "Auth, limit, HTTP"), h("span", {}, fmtMs(other))));

  let note;
  if (d.cache_hit) {
    note = "Served from the Redis cache: someone already ran this task on these exact bytes with this model version, so the queue and GPU were skipped.";
  } else {
    const q = t.queue?.dur ?? 0, g = t.gpu?.dur ?? 0;
    const why = q > 30 ? " (mostly waiting for the GPU to finish earlier work)" : " (the batcher's short wait for companions)";
    note = `Ran on the GPU in a batch of ${d.batch_size}. It spent ${fmtMs(q)} in the queue${why}, then the forward pass took ${fmtMs(g)}` +
      (d.batch_size > 1 ? `, about ${fmtMs(g / d.batch_size)} per image.` : ".");
    if ((t.store?.dur ?? 0) > 15) note += " First time this image was seen for your account, so it was uploaded to S3 storage.";
    if (g > 1500) note += " (The first GPU call after startup is slow while CUDA warms up.)";
  }

  return h("div", {},
    h("p", { class: "trace-title" }, h("span", {}, "Where the time went"), h("span", {}, `${fmtMs(total)} round trip`)),
    bar, list, h("p", { class: "trace-note" }, note));
}

function rawView(r) {
  const headers = ["X-Request-ID", "Server-Timing", "Retry-After"]
    .map((k) => [k, r.headers.get(k)]).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join("\n");
  return h("details", { class: "raw" }, h("summary", {}, "Raw response"),
    h("pre", {}, `HTTP ${r.status}\n${headers}\n\n${JSON.stringify(r.data, null, 2)}`));
}

// ---------- batching lab ----------
$("#burst-count").addEventListener("input", (e) => ($("#burst-count-out").textContent = e.target.value));

async function sourceCanvas() {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (currentFile) {
    const bmp = await createImageBitmap(currentFile);
    const scale = Math.min(1, 800 / Math.max(bmp.width, bmp.height));
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  } else {
    // A generated scene with text, so both captioning and OCR have work to do.
    canvas.width = 640; canvas.height = 400;
    ctx.fillStyle = "#87bfe8"; ctx.fillRect(0, 0, 640, 400);
    ctx.fillStyle = "#3c9c3c"; ctx.fillRect(0, 300, 640, 100);
    ctx.fillStyle = "#f4d53a"; ctx.beginPath(); ctx.arc(530, 80, 50, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#a83c28"; ctx.fillRect(120, 180, 180, 120);
    ctx.fillStyle = "#5a2a1e"; ctx.beginPath(); ctx.moveTo(100, 180); ctx.lineTo(210, 100); ctx.lineTo(320, 180); ctx.fill();
    ctx.fillStyle = "#111"; ctx.font = "bold 28px sans-serif"; ctx.fillText("FARM OPEN 9-5", 330, 250);
  }
  return canvas;
}

/** N copies of the image, each with one random pixel changed: same content, new SHA-256. */
async function makeVariants(n) {
  const canvas = await sourceCanvas();
  const ctx = canvas.getContext("2d");
  const blobs = [];
  for (let i = 0; i < n; i++) {
    const x = Math.floor(Math.random() * canvas.width), y = Math.floor(Math.random() * canvas.height);
    ctx.fillStyle = `rgb(${(Math.random() * 255) | 0},${(Math.random() * 255) | 0},${(Math.random() * 255) | 0})`;
    ctx.fillRect(x, y, 1, 1);
    blobs.push(await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.92)));
  }
  return blobs;
}

$("#burst-btn").addEventListener("click", async () => {
  const btn = $("#burst-btn");
  const n = Number($("#burst-count").value);
  const task = $("#burst-task").value;
  btn.classList.add("busy");
  btn.disabled = true;
  try {
    const blobs = await makeVariants(n); // prepared first so all requests leave together
    const t0 = performance.now();
    const runs = await Promise.all(blobs.map(async (blob, i) => {
      const sent = performance.now() - t0;
      const r = await infer(task, blob, `variant-${i}.jpg`);
      return { i, sent, recv: performance.now() - t0, r };
    }));
    renderLab(runs, task, performance.now() - t0);
  } finally {
    btn.classList.remove("busy");
    btn.disabled = false;
  }
});

function renderLab(runs, task, wallMs) {
  const ok = runs.filter((x) => x.r.ok);
  const limited = runs.filter((x) => x.r.status === 429).length;
  const failed = runs.length - ok.length - limited;
  const batches = new Map(); // server batch id -> runs
  for (const x of ok) {
    const id = x.r.timing.gpu?.desc ?? `solo-${x.i}`;
    if (!batches.has(id)) batches.set(id, []);
    batches.get(id).push(x);
  }
  const passes = batches.size;
  const gpuPerImage = ok.length ? ok.reduce((a, x) => a + (x.r.timing.gpu?.dur ?? 0) / (x.r.data.batch_size || 1), 0) / ok.length : 0;
  const tiles = h("div", { class: "tiles" },
    tile("Requests sent", runs.length, `${task}`),
    tile("Answered", ok.length, limited ? `${limited} rate limited (429)` : failed ? `${failed} failed` : "all succeeded"),
    tile("GPU passes", passes, ok.length ? `${(ok.length / Math.max(passes, 1)).toFixed(1)} images per pass` : ""),
    tile("GPU time per image", fmtMs(gpuPerImage), "forward pass ÷ batch size"),
    tile("Wall time", fmtMs(wallMs), ok.length ? `${(ok.length / (wallMs / 1000)).toFixed(1)} answers/s` : ""));

  const box = $("#lab-results");
  box.replaceChildren(tiles, h("div", { class: "card" },
    h("h3", {}, "Timeline: one row per request, grouped by the GPU pass it ran in"),
    h("div", { class: "legend" },
      ...["decode", "cache", "store", "queue", "gpu", "save"].map((k) => h("span", {}, h("i", { style: `background:${stageColor(k)}` }), STAGES.find((s) => s.key === k).label)),
      h("span", {}, h("i", { class: "line" }), "Auth, rate limit, HTTP")),
    gantt(runs, batches, wallMs),
    h("p", { class: "hint" }, "Requests in the same group finished their GPU segment together: they were one forward pass. Try 1 request a few times, then a burst of 8, and compare the GPU time per image."),
    h("p", { class: "hint" }, "Why not 8 per pass? A browser keeps at most 6 connections open to one server (HTTP/1.1), so a big burst arrives in waves of up to 6, and whoever lands within the same 10 ms window shares a pass. The Locust load test (loadtest/) has no such limit.")));
}

function tile(label, value, sub) {
  return h("div", { class: "tile" }, h("div", { class: "tile-label" }, label), h("div", { class: "tile-value" }, value), sub ? h("div", { class: "tile-sub" }, sub) : null);
}

function gantt(runs, batches, wallMs) {
  const width = Math.max(560, $("#lab-results").clientWidth - 40);
  const labelW = 118, rowH = 12, rowGap = 5, groupGap = 14, axisH = 22;
  // Order groups by when their GPU pass finished.
  const gpuEnd = (x) => x.recv - (x.r.timing.save?.dur ?? 0);
  const groups = [...batches.entries()].sort((a, b) => Math.min(...a[1].map(gpuEnd)) - Math.min(...b[1].map(gpuEnd)));
  const failedRuns = runs.filter((x) => !x.r.ok);
  if (failedRuns.length) groups.push(["failed", failedRuns]);

  let y = 4;
  const rows = [];
  for (const [id, members] of groups) {
    rows.push({ type: "label", y, id, members });
    for (const x of members.sort((a, b) => a.i - b.i)) { rows.push({ type: "run", y, x }); y += rowH + rowGap; }
    y += groupGap;
  }
  const height = y + axisH;
  const xs = (ms) => labelW + (ms / wallMs) * (width - labelW - 8);
  const svg = s("svg", { class: "gantt", viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": "Per-request timeline grouped by GPU pass" });

  const grid = s("g", { class: "grid" });
  const step = niceStep(wallMs / 6);
  for (let t = 0; t <= wallMs; t += step) {
    grid.append(s("line", { x1: xs(t), x2: xs(t), y1: 0, y2: height - axisH }));
    svg.append(s("text", { x: xs(t), y: height - 6, "text-anchor": "middle" }, t === 0 ? "0" : fmtMs(t)));
  }
  svg.prepend(grid);

  let pass = 0;
  for (const row of rows) {
    if (row.type === "label") {
      const n = row.members.length;
      const label = row.id === "failed" ? `Rejected · ${n}` : `Pass ${++pass} · ${n} img${n > 1 ? "s" : ""}`;
      svg.append(s("text", { x: 0, y: row.y + rowH - 1, class: "batch-label" }, label));
      continue;
    }
    const { x } = row;
    const cy = row.y + rowH / 2;
    svg.append(s("line", { x1: xs(x.sent), x2: xs(x.recv), y1: cy, y2: cy, stroke: "var(--text-3)", "stroke-width": 1.5, "stroke-linecap": "round" }));
    if (!x.r.ok) {
      const mark = s("rect", { x: xs(x.recv) - 3, y: row.y, width: 6, height: rowH, rx: 2, fill: "var(--critical)" });
      hoverTip(mark, () => `<b>Request ${x.i + 1}: ${x.r.status}</b><br>${esc(errMsg(x.r))}`);
      svg.append(mark);
      continue;
    }
    // Rebuild stage positions backwards from the response time (localhost: network ≈ 0).
    let end = x.recv;
    for (const st of [...STAGES].reverse()) {
      const dur = x.r.timing[st.key]?.dur;
      if (dur == null) continue;
      const start = end - dur;
      const rect = s("rect", { x: xs(start), y: row.y, width: Math.max(1.5, xs(end) - xs(start)), height: rowH, rx: 2, fill: stageColor(st.key) });
      hoverTip(rect, () => `<b>Request ${x.i + 1} · ${esc(st.label)}</b> ${fmtMs(dur)}<br>batch of ${x.r.data.batch_size} · ${x.r.data.cache_hit ? "cache hit" : "GPU"}<br>total ${fmtMs(x.recv - x.sent)}`);
      svg.append(rect);
      end = start;
    }
  }
  return svg;
}

function niceStep(raw) {
  const pow = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-6)));
  const n = raw / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

// ---------- history ----------
let historyCursor = null;
async function loadHistory(reset) {
  if (reset) {
    historyCursor = null;
    $("#history-table tbody").replaceChildren();
    $("#history-detail").replaceChildren();
    loadStats();
  }
  const r = await api(`/v1/requests?limit=20${historyCursor ? `&cursor=${historyCursor}` : ""}`);
  if (!r.ok) { toast(errMsg(r)); return; }
  const tbody = $("#history-table tbody");
  if (reset && !r.data.items.length) {
    tbody.append(h("tr", {}, h("td", { colspan: 8, class: "hint" }, "No requests yet. Analyze an image first.")));
  }
  for (const item of r.data.items) {
    const ok = item.status === "ok";
    const tr = h("tr", { tabindex: 0 },
      h("td", {}, item.id),
      h("td", { title: new Date(item.created_at).toLocaleString() }, timeAgo(item.created_at)),
      h("td", {}, TASK_LABEL[item.task] ?? item.task),
      h("td", {}, h("span", { class: `status ${ok ? "ok" : "bad"}` }, iconEl(ok ? "ok" : "bad"), item.status)),
      h("td", {}, item.cache_hit ? "Cache" : ok ? "GPU" : "–"),
      h("td", { class: "num" }, item.batch_size ?? "–"),
      h("td", { class: "num" }, item.latency_ms != null ? `${item.latency_ms} ms` : "–"),
      h("td", { class: "result" }, item.result?.text ?? item.error ?? ""));
    const open = () => showDetail(item, tr);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => e.key === "Enter" && open());
    tbody.append(tr);
  }
  historyCursor = r.data.next_cursor;
  $("#history-more").hidden = !historyCursor;
}
$("#history-more").addEventListener("click", () => loadHistory(false));
$("#history-refresh").addEventListener("click", () => loadHistory(true));

async function loadStats() {
  const r = await api("/v1/stats/me");
  if (!r.ok) return;
  const d = r.data;
  $("#stats-tiles").replaceChildren(
    tile("Total requests", d.total_requests, `${d.requests_last_24h} in the last 24 h`),
    tile("Cache hit rate", `${Math.round(d.cache_hit_rate * 100)}%`, "answered without the GPU"),
    tile("Average latency", d.avg_latency_ms != null ? fmtMs(d.avg_latency_ms) : "–", "server time, all requests"),
    tile("p95 latency", d.p95_latency_ms_last_hour != null ? fmtMs(d.p95_latency_ms_last_hour) : "–", "last hour: 95% were faster"),
    tile("By task", d.by_task.map((t) => t.requests).join(" / ") || "–", d.by_task.map((t) => TASK_LABEL[t.task] ?? t.task).join(" / ") || "no requests yet"));
}

async function showDetail(item, tr) {
  for (const row of $$("#history-table tbody tr")) row.classList.toggle("selected", row === tr);
  const box = $("#history-detail");
  const img = h("img", { alt: "Stored image" });
  const link = h("a", { target: "_blank", rel: "noopener" }, "Open the pre-signed URL");
  box.replaceChildren(h("div", { class: "card detail" },
    h("div", {}, img, h("p", { class: "hint" }, link, " · valid 15 minutes, served straight from S3 storage, not through the API")),
    h("div", {},
      h("h3", {}, `Request #${item.id}: ${TASK_LABEL[item.task] ?? item.task}`),
      h("p", { class: `result-text ${item.task === "ocr" ? "ocr" : ""}` }, item.result?.text ?? item.error ?? ""),
      h("dl", {},
        h("dt", {}, "Status"), h("dd", {}, item.status),
        h("dt", {}, "Answered by"), h("dd", {}, item.cache_hit ? "Redis cache" : `GPU, batch of ${item.batch_size ?? "?"}`),
        h("dt", {}, "Latency"), h("dd", {}, item.latency_ms != null ? `${item.latency_ms} ms` : "–"),
        h("dt", {}, "Image id"), h("dd", {}, item.image_id),
        h("dt", {}, "Created"), h("dd", {}, new Date(item.created_at).toLocaleString())))));
  const r = await api(`/v1/images/${item.image_id}/url`);
  if (r.ok) { img.src = r.data.url; link.href = r.data.url; }
  else { link.textContent = `Image unavailable (${r.status})`; }
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------- system (live metrics) ----------
const HISTORY_LEN = 60; // 2 minutes at one sample per 2 s
const samples = []; // {t, inferTotal, queue}
let metricsSnapshot = null;

function parseProm(text) {
  const out = {};
  for (const line of text.split("\n")) {
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^([a-zA-Z_:][\w:]*)(\{([^}]*)\})?\s+([^\s]+)/);
    if (!m) continue;
    const labels = {};
    if (m[3]) for (const pair of m[3].matchAll(/(\w+)="((?:[^"\\]|\\.)*)"/g)) labels[pair[1]] = pair[2];
    (out[m[1]] ??= []).push({ labels, value: parseFloat(m[4]) });
  }
  return out;
}
const sum = (rows = [], pred = () => true) => rows.filter((r) => pred(r.labels)).reduce((a, r) => a + r.value, 0);

/** Quantile from cumulative Prometheus buckets, interpolating inside the bucket. */
function quantile(bucketRows, q, pred = () => true) {
  const byLe = new Map();
  for (const r of bucketRows ?? []) if (pred(r.labels)) byLe.set(r.labels.le, (byLe.get(r.labels.le) ?? 0) + r.value);
  const pts = [...byLe.entries()].map(([le, c]) => [le === "+Inf" ? Infinity : parseFloat(le), c]).sort((a, b) => a[0] - b[0]);
  const total = pts.at(-1)?.[1] ?? 0;
  if (!total) return null;
  const target = q * total;
  let prevLe = 0, prevC = 0;
  for (const [le, c] of pts) {
    if (c >= target) {
      if (le === Infinity) return prevLe;
      return prevLe + ((target - prevC) / Math.max(c - prevC, 1e-9)) * (le - prevLe);
    }
    prevLe = le; prevC = c;
  }
  return prevLe;
}

async function pollMetrics() {
  let text;
  try { const res = await fetch("/metrics"); if (!res.ok) return; text = await res.text(); } catch { return; }
  const m = parseProm(text);
  const now = performance.now();
  samples.push({
    t: now,
    inferTotal: sum(m.http_requests_total, (l) => l.route === "/v1/infer/{task}"),
    queue: sum(m.queue_depth),
  });
  if (samples.length > HISTORY_LEN + 1) samples.shift();
  metricsSnapshot = { m, text };
  if (activeTab === "system") renderSystem();
}
setInterval(() => document.visibilityState === "visible" && pollMetrics(), 2000);

function rpsSeries() {
  const out = [];
  for (let i = 1; i < samples.length; i++) {
    const dt = (samples[i].t - samples[i - 1].t) / 1000;
    out.push({ t: samples[i].t, v: Math.max(0, (samples[i].inferTotal - samples[i - 1].inferTotal) / dt) });
  }
  return out;
}

function renderSystem() {
  if (!metricsSnapshot) { pollMetrics(); return; }
  const { m, text } = metricsSnapshot;
  const hits = sum(m.cache_hits_total), misses = sum(m.cache_misses_total);
  const passes = sum(m.batch_size_count), imgs = sum(m.batch_size_sum);
  const lat = m.inference_latency_seconds_bucket;
  const p50 = quantile(lat, 0.5, (l) => l.cache === "miss");
  const p95 = quantile(lat, 0.95, (l) => l.cache === "miss");
  const p50hit = quantile(lat, 0.5, (l) => l.cache === "hit");
  const rps = rpsSeries();

  $("#system-tiles").replaceChildren(
    tile("Inference req/s", rps.length ? rps.at(-1).v.toFixed(1) : "–", "last 2 seconds"),
    tile("Queue depth", sum(m.queue_depth), "waiting for the GPU right now"),
    tile("Cache hit rate", hits + misses ? `${Math.round((hits / (hits + misses)) * 100)}%` : "–", `${hits} hits · ${misses} misses`),
    tile("GPU path p50", p50 != null ? fmtMs(p50 * 1000) : "–", "cache misses: half were faster"),
    tile("GPU path p95", p95 != null ? fmtMs(p95 * 1000) : "–", "95% were faster (tail latency)"),
    tile("Cache path p50", p50hit != null ? fmtMs(p50hit * 1000) : "–", "cache hits"),
    tile("Avg batch size", passes ? (imgs / passes).toFixed(2) : "–", `${passes} GPU passes total`));

  lineChart($("#chart-rps"), rps, { fmt: (v) => `${v.toFixed(1)} req/s`, label: "requests per second" });
  lineChart($("#chart-queue"), samples.map((x) => ({ t: x.t, v: x.queue })), { fmt: (v) => `${v} waiting`, label: "queue depth", integer: true });
  batchChart($("#chart-batches"), m.batch_size_bucket ?? []);
  const ours = /^(http_requests_total|inference_latency_seconds|batch_size|cache_hits_total|cache_misses_total|queue_depth)/;
  $("#raw-metrics").textContent = text.split("\n").filter((l) => ours.test(l.replace(/^# (HELP|TYPE) /, ""))).join("\n");
}

function renderReady() {
  const box = $("#ready-detail");
  if (!lastReady) return;
  const checks = lastReady.data?.checks ?? {};
  const desc = { model: "Florence-2 loaded on the GPU", postgres: "SELECT 1 within 1 s", redis: "PING within 1 s" };
  box.replaceChildren(
    ...Object.entries(desc).map(([k, d]) => h("div", { class: `check-row ${checks[k] ? "ok" : "bad"}` },
      iconEl(checks[k] ? "ok" : "bad"), h("span", {}, k[0].toUpperCase() + k.slice(1)), h("span", {}, checks[k] ? d : "not ready"))),
    h("p", { class: "hint" }, `/readyz → ${lastReady.status}. A load balancer would ${lastReady.status === 200 ? "send traffic here" : "hold traffic back"}. /healthz (liveness) only checks that the process answers.`));
}

/** Single-series line chart with crosshair tooltip. Points: [{t, v}] */
function lineChart(container, points, { fmt, label, integer = false }) {
  const W = Math.max(300, container.clientWidth || 400), H = 170, L = 34, R = 8, T = 8, B = 22;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": label });
  const { max: yMax, step: yStep } = niceAxis(Math.max(...points.map((p) => p.v), 0), integer);
  const now = performance.now(), span = HISTORY_LEN * 2000;
  const x = (t) => L + ((t - (now - span)) / span) * (W - L - R);
  const y = (v) => T + (1 - v / yMax) * (H - T - B);

  const grid = s("g", { class: "grid" });
  for (let v = 0; v <= yMax + 1e-9; v += yStep) {
    grid.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    svg.append(s("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, +v.toFixed(2)));
  }
  svg.prepend(grid);
  svg.append(s("text", { x: L, y: H - 4 }, "−2 min"), s("text", { x: W - R, y: H - 4, "text-anchor": "end" }, "now"));

  if (points.length > 1) {
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    svg.append(s("path", { d: `${d}L${x(points.at(-1).t)},${y(0)}L${x(points[0].t)},${y(0)}Z`, fill: "var(--series-fill)" }));
    svg.append(s("path", { d, fill: "none", stroke: "var(--series)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  } else {
    svg.append(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, "collecting samples…"));
  }

  const cross = s("line", { class: "crosshair", y1: T, y2: H - B, visibility: "hidden" });
  const dot = s("circle", { class: "dot", r: 4, visibility: "hidden" });
  const hit = s("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
  svg.append(cross, dot, hit);
  hit.addEventListener("pointermove", (e) => {
    if (!points.length) return;
    const box = svg.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const p = points.reduce((a, b) => (Math.abs(x(b.t) - px) < Math.abs(x(a.t) - px) ? b : a));
    cross.setAttribute("x1", x(p.t)); cross.setAttribute("x2", x(p.t)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x(p.t)); dot.setAttribute("cy", y(p.v)); dot.setAttribute("visibility", "visible");
    const ago = Math.round((now - p.t) / 1000);
    tip.show(e, `<b>${esc(fmt(p.v))}</b><br>${ago <= 2 ? "now" : `${ago} s ago`}`);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); });
  container.replaceChildren(svg);
}

/** Bar chart of GPU passes per batch-size bucket (from the cumulative histogram). */
function batchChart(container, rows) {
  const W = Math.max(300, container.clientWidth || 400), H = 170, L = 34, R = 8, T = 8, B = 22;
  const cum = rows.map((r) => [r.labels.le === "+Inf" ? Infinity : parseFloat(r.labels.le), r.value]).sort((a, b) => a[0] - b[0]);
  const buckets = [];
  let prevLe = 0, prevC = 0;
  for (const [le, c] of cum) {
    if (le === Infinity) break;
    const lo = prevLe + 1;
    buckets.push({ label: lo === le ? `${le}` : `${lo}–${le}`, count: c - prevC });
    prevLe = le; prevC = c;
  }
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": "GPU passes by batch size" });
  const total = buckets.reduce((a, b) => a + b.count, 0);
  if (!total) {
    svg.append(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, "no GPU passes yet"));
    container.replaceChildren(svg);
    return;
  }
  const { max: yMax, step: yStep } = niceAxis(Math.max(...buckets.map((b) => b.count)), true);
  const y = (v) => T + (1 - v / yMax) * (H - T - B);
  const grid = s("g", { class: "grid" });
  for (let v = 0; v <= yMax + 1e-9; v += yStep) {
    grid.append(s("line", { x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    svg.append(s("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, v));
  }
  svg.append(grid);
  const slot = (W - L - R) / buckets.length, bw = Math.min(42, slot - 2);
  buckets.forEach((b, i) => {
    const cx = L + slot * i + slot / 2;
    const top = y(b.count), base = y(0);
    if (b.count > 0) {
      // 4px rounded data end, square at the baseline.
      const hgt = base - top, r = Math.min(4, hgt, bw / 2), x0 = cx - bw / 2;
      svg.append(s("path", { d: `M${x0},${base}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + bw - r}Q${x0 + bw},${top} ${x0 + bw},${top + r}V${base}Z`, fill: "var(--series)" }));
    }
    svg.append(s("text", { x: cx, y: H - 6, "text-anchor": "middle" }, b.label));
    const hit = s("rect", { x: L + slot * i, y: T, width: slot, height: H - T - B, fill: "transparent" });
    hoverTip(hit, () => `<b>Batch size ${esc(b.label)}</b><br>${b.count} GPU pass${b.count === 1 ? "" : "es"} (${Math.round((b.count / total) * 100)}%)`);
    svg.append(hit);
  });
  container.replaceChildren(svg);
}

/** About four evenly spaced ticks on round numbers (1, 2, 5 × 10^n); whole numbers for counts. */
function niceAxis(maxValue, integer = false) {
  const floor = integer ? 4 : 1;
  const step = Math.max(integer ? 1 : 0, niceStep(Math.max(maxValue, floor) / 4));
  return { step, max: Math.max(step * 4, Math.ceil(maxValue / step) * step) };
}

// ---------- start ----------
showApp();
pollHealth();
pollMetrics();
const savedTab = store.get("vs.tab");
if (savedTab && savedTab !== "analyze") $(`[role=tab][data-tab="${savedTab}"]`)?.click();
