// Sahayak frontend: pick a language → push-to-talk turns → answers write themselves onto the form.
const $ = (id) => document.getElementById(id);
let session = null;
let recorder = null;
let chunks = [];
let busy = false;
let lastAudio = null;
let wasDone = false;

// "Complete" in each script, for the rubber stamp.
const COMPLETE = { "hi-IN": "पूर्ण", "mr-IN": "पूर्ण", "te-IN": "పూర్తి", "ta-IN": "முடிந்தது", "kn-IN": "ಪೂರ್ಣ",
  "bn-IN": "সম্পূর্ণ", "gu-IN": "પૂર્ણ", "pa-IN": "ਪੂਰਾ", "ml-IN": "പൂർത്തിയായി", "od-IN": "ସମ୍ପୂର୍ଣ୍ଣ", "en-IN": "" };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

// ------------------------------------------------------------------ boot
(async function boot() {
  const cfg = await api("/api/config");
  $("mock-banner").hidden = !cfg.mock;
  $("form-title-welcome").textContent = cfg.form_title;
  for (const l of cfg.languages) {
    const b = document.createElement("button");
    b.setAttribute("role", "listitem");
    b.innerHTML = `<span class="speak"></span><span class="lname"></span>`;
    b.querySelector(".speak").textContent = l.speak;
    b.querySelector(".lname").textContent = l.code === "en-IN" ? "English" : `${l.name}, ${l.english}`;
    b.onclick = () => start(l);
    $("lang-grid").append(b);
  }
})();

async function start(lang) {
  $("welcome").hidden = true;
  $("workspace").hidden = false;
  $("lang-pill").textContent = lang.code === "en-IN" ? "English" : `${lang.name} (${lang.english})`;
  $("stamp-local").textContent = COMPLETE[lang.code] || "";
  $("chat").innerHTML = "";
  $("question").textContent = "";
  setBusy(true, "Getting your form ready");
  try {
    handle(await api("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: lang.code }),
    }));
  } catch (e) { addMsg("err", e.message); setBusy(false, "Tap the mic to answer"); }
}
$("restart").onclick = () => location.reload();

// ------------------------------------------------------------------ rendering
function addMsg(kind, text) {
  const li = document.createElement("li");
  li.className = kind;
  li.textContent = text;
  $("chat").append(li);
  $("chat").scrollTop = $("chat").scrollHeight;
}

function renderForm(state, changed = []) {
  session = state;
  $("form-title").textContent = state.form.title;
  const firstMissing = state.form.fields.find((f) => !state.values[f.key]);
  $("fields").innerHTML = "";
  for (const f of state.form.fields) {
    const li = document.createElement("li");
    if (!state.done && firstMissing && f.key === firstMissing.key) li.classList.add("current");

    const label = document.createElement("div");
    label.className = "f-label";
    label.textContent = f.label;
    if (f.local_label && f.local_label !== f.label) {
      const local = document.createElement("span");
      local.className = "local";
      local.textContent = f.local_label;
      label.append(local);
    }

    const v = document.createElement("div");
    v.className = "f-value";
    v.contentEditable = "true";
    v.spellcheck = false;
    v.dataset.hint = f.hint;
    v.setAttribute("aria-label", f.label);
    v.textContent = state.values[f.key] || "";
    if (changed.includes(f.key) && v.textContent) v.classList.add("writing");
    v.onblur = () => saveEdit(f.key, v.textContent);
    v.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); v.blur(); } };

    li.append(label, v);
    $("fields").append(li);
  }
  const total = state.form.fields.length;
  const filled = state.form.fields.filter((f) => state.values[f.key]).length;
  $("progress-text").innerHTML = `<b>${filled}/${total}</b>answered`;

  $("stamp").hidden = !state.done;
  $("print").hidden = !state.done;
  if (state.done && !wasDone) {
    $("stamp").classList.remove("land");
    void $("stamp").offsetWidth; // restart the animation
    $("stamp").classList.add("land");
  }
  wasDone = state.done;
}

async function saveEdit(field, value) {
  if (!session || (session.values[field] || "") === value.trim()) return;
  try {
    renderForm(await api(`/api/session/${session.id}/field`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, value }),
    }), [field]);
  } catch (e) { addMsg("err", e.message); }
}

function handle(r) {
  // The previous question moves into the history; the new one takes the big slot.
  const prev = $("question").textContent;
  if (prev) addMsg("bot", prev);
  if (r.heard) addMsg("user", r.heard);
  if (r.error) addMsg("err", r.error);
  if (r.reply) {
    $("question").textContent = r.reply;
    $("question").classList.toggle("long", r.reply.length > 110);
  }

  renderForm(r.state, r.changed || []);
  const t = r.timings || {};
  const names = { stt_s: "Listening", doc_s: "Reading", llm_s: "Thinking", tts_s: "Voice" };
  $("timings").textContent = Object.keys(names).filter((k) => t[k] != null)
    .map((k) => `${names[k]} ${t[k]}s`).join(", ");

  lastAudio = r.audio_b64 || null;
  $("replay").hidden = !lastAudio;
  if (lastAudio) play(lastAudio);
  else setBusy(false, nextPrompt());
}

function nextPrompt() { return session?.done ? "Your form is complete" : "Tap the mic to answer"; }

// ------------------------------------------------------------------ audio out
function play(b64) {
  const p = $("player");
  p.src = `data:audio/wav;base64,${b64}`;
  setBusy(false, "Speaking. Tap the mic to interrupt");
  p.onended = () => setStatus(nextPrompt());
  p.play().catch(() => setStatus("Press “Hear it again” to listen"));
}
$("replay").onclick = () => lastAudio && play(lastAudio);

// ------------------------------------------------------------------ audio in (push-to-talk)
function pickMime() {
  for (const m of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

async function startRec() {
  if (busy || recorder || !session) return;
  $("player").pause(); // barge-in: stop Sahayak talking
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = () => { stream.getTracks().forEach((t) => t.stop()); sendAudio(recorder.mimeType); };
    recorder.start();
    $("mic").classList.add("rec");
    $("mic").setAttribute("aria-label", "Tap to finish");
    setStatus("Listening. Tap again when you finish");
  } catch (e) {
    addMsg("err", "The microphone is blocked. Allow microphone access in the browser, or type your answer.");
  }
}

function stopRec() {
  if (!recorder) return;
  $("mic").classList.remove("rec");
  $("mic").setAttribute("aria-label", "Tap to answer");
  recorder.stop();
}

async function sendAudio(mime) {
  recorder = null;
  const blob = new Blob(chunks, { type: mime || "audio/webm" });
  if (blob.size < 1200) { setStatus("That was too short. Tap and speak again"); return; }
  const ext = (mime || "").includes("mp4") ? "m4a" : (mime || "").includes("ogg") ? "ogg" : "webm";
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("audio", blob, `speech.${ext}`);
  await turn(fd, "Understanding your answer");
}

async function turn(fd, label) {
  setBusy(true, label);
  try { handle(await api("/api/turn", { method: "POST", body: fd })); }
  catch (e) { addMsg("err", e.message); setBusy(false, nextPrompt()); }
}

$("mic").onclick = () => (recorder ? stopRec() : startRec());
// Hold-Space-to-talk only when nothing else has focus, so typing never opens the mic.
const typing = () => ![document.body, $("mic")].includes(document.activeElement);
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !typing() && session) { e.preventDefault(); startRec(); }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && !typing()) { e.preventDefault(); stopRec(); }
});

$("text-form").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !session || busy) return;
  $("text-input").value = "";
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("text", text);
  await turn(fd, "Thinking");
};

$("doc-input").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file || !session) return;
  addMsg("sys", `Reading ${file.name}`);
  const fd = new FormData();
  fd.append("session_id", session.id);
  fd.append("file", file);
  setBusy(true, "Reading your document");
  try { handle(await api("/api/document", { method: "POST", body: fd })); }
  catch (err) { addMsg("err", err.message); setBusy(false, nextPrompt()); }
};

$("print").onclick = () => window.print();

// ------------------------------------------------------------------ status
function setStatus(t) { $("status").textContent = t; }
function setBusy(b, t) {
  busy = b;
  $("mic").disabled = b;
  $("mic").classList.toggle("thinking", b);
  if (t) setStatus(t);
}
