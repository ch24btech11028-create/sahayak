// Sahayak frontend: language pick → push-to-talk turns → live-filling paper form.
const $ = (id) => document.getElementById(id);
let session = null;
let recorder = null;
let chunks = [];
let busy = false;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ------------------------------------------------------------------ boot
(async function boot() {
  const cfg = await api("/api/config");
  $("mock-banner").hidden = !cfg.mock;
  $("form-title-welcome").textContent = cfg.form_title;
  for (const l of cfg.languages) {
    const b = document.createElement("button");
    b.innerHTML = `<b>${l.name}</b><span>${l.english}</span>`;
    b.onclick = () => start(l);
    $("lang-grid").append(b);
  }
})();

async function start(lang) {
  $("welcome").hidden = true;
  $("workspace").hidden = false;
  $("restart").hidden = false;
  $("lang-pill").hidden = false;
  $("lang-pill").textContent = `${lang.name} · ${lang.english}`;
  $("chat").innerHTML = "";
  setBusy(true, "Starting…");
  try {
    handle(await api("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: lang.code }),
    }));
  } catch (e) { addMsg("err", e.message); setBusy(false, "Ready"); }
}
$("restart").onclick = () => location.reload();

// ------------------------------------------------------------------ rendering
function addMsg(kind, text, audio) {
  const el = document.createElement("div");
  el.className = `msg ${kind}`;
  el.textContent = text;
  if (audio) {
    const r = document.createElement("button");
    r.className = "replay"; r.title = "Play again"; r.textContent = "🔊";
    r.onclick = () => play(audio);
    el.append(r);
  }
  $("chat").append(el);
  $("chat").scrollTop = $("chat").scrollHeight;
}

function renderForm(state, changed = []) {
  session = state;
  $("form-title").textContent = state.form.title;
  const firstMissing = state.form.fields.find((f) => !state.values[f.key]);
  $("fields").innerHTML = "";
  for (const f of state.form.fields) {
    const li = document.createElement("li");
    if (firstMissing && f.key === firstMissing.key) li.classList.add("current");
    if (changed.includes(f.key)) li.classList.add("flash");
    const local = f.local_label && f.local_label !== f.label ? `<i>${f.local_label}</i>` : "";
    li.innerHTML = `<div class="f-label">${f.label}${local}</div>`;
    const v = document.createElement("div");
    v.className = "f-value"; v.contentEditable = "true"; v.textContent = state.values[f.key] || "";
    v.onblur = () => saveEdit(f.key, v.textContent);
    v.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); v.blur(); } };
    li.append(v);
    $("fields").append(li);
  }
  const total = state.form.fields.length;
  const filled = state.form.fields.filter((f) => state.values[f.key]).length;
  $("progress-bar").style.width = `${(filled / total) * 100}%`;
  $("progress-text").textContent = `${filled} of ${total} filled`;
  $("stamp").hidden = !state.done;
  $("print").hidden = !state.done;
}

async function saveEdit(field, value) {
  if (!session || (session.values[field] || "") === value.trim()) return;
  renderForm(await api(`/api/session/${session.id}/field`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ field, value }),
  }), [field]);
}

function handle(r) {
  if (r.heard) addMsg("user", r.heard);
  if (r.reply) addMsg("bot", r.reply, r.audio_b64);
  if (r.error) addMsg("err", r.error);
  renderForm(r.state, r.changed || []);
  const t = r.timings || {};
  $("timings").textContent = ["stt_s", "doc_s", "llm_s", "tts_s"]
    .filter((k) => t[k] != null).map((k) => `${k.replace("_s", "").toUpperCase()} ${t[k]}s`).join(" · ");
  if (r.audio_b64) play(r.audio_b64); else setBusy(false, "Ready");
}

// ------------------------------------------------------------------ audio out
function play(b64) {
  const p = $("player");
  p.src = `data:audio/wav;base64,${b64}`;
  setBusy(false, "Speaking… (tap the mic to interrupt)");
  p.onended = () => setStatus(session?.done ? "Form complete ✓" : "Your turn: tap the mic");
  p.play().catch(() => setStatus("Tap 🔊 to hear the reply"));
}

// ------------------------------------------------------------------ audio in (push-to-talk)
function pickMime() {
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

async function startRec() {
  if (busy || recorder) return;
  $("player").pause(); // barge-in: stop the bot talking
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = () => { stream.getTracks().forEach((t) => t.stop()); sendAudio(recorder.mimeType); };
    recorder.start();
    $("mic").classList.add("rec");
    setStatus("Listening… tap again when done");
  } catch (e) {
    addMsg("err", "Microphone not available: " + e.message);
  }
}

function stopRec() {
  if (!recorder) return;
  $("mic").classList.remove("rec");
  recorder.stop();
}

async function sendAudio(mime) {
  recorder = null;
  const blob = new Blob(chunks, { type: mime || "audio/webm" });
  if (blob.size < 1200) { setStatus("Too short, try again"); return; }
  const ext = (mime || "").includes("mp4") ? "m4a" : (mime || "").includes("ogg") ? "ogg" : "webm";
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("audio", blob, `speech.${ext}`);
  await turn(fd, "Understanding…");
}

async function turn(fd, label) {
  setBusy(true, label);
  try { handle(await api("/api/turn", { method: "POST", body: fd })); }
  catch (e) { addMsg("err", e.message); setBusy(false, "Ready"); }
}

$("mic").onclick = () => (recorder ? stopRec() : startRec());
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && document.activeElement === document.body && session) { e.preventDefault(); startRec(); }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && document.activeElement === document.body) { e.preventDefault(); stopRec(); }
});

$("text-form").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !session || busy) return;
  $("text-input").value = "";
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("text", text);
  await turn(fd, "Thinking…"); // the reply echoes `heard`, which shows the typed text
};

$("doc-input").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file || !session) return;
  addMsg("sys", `📎 Reading ${file.name}…`);
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("file", file);
  setBusy(true, "Reading document with Sarvam Vision…");
  try { handle(await api("/api/document", { method: "POST", body: fd })); }
  catch (err) { addMsg("err", err.message); setBusy(false, "Ready"); }
};

$("print").onclick = () => window.print();

// ------------------------------------------------------------------ status
function setStatus(t) { $("status").textContent = t; }
function setBusy(b, t) { busy = b; $("mic").disabled = b; if (t) setStatus(t); }
