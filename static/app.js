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

// ------------------------------------------------------------------ boot: pick a language
let lang = null;

(async function boot() {
  const cfg = await api("/api/config");
  $("mock-banner").hidden = !cfg.mock;
  for (const l of cfg.languages) {
    const b = document.createElement("button");
    b.setAttribute("role", "listitem");
    b.innerHTML = `<span class="speak"></span><span class="lname"></span>`;
    b.querySelector(".speak").textContent = l.speak;
    b.querySelector(".lname").textContent = l.code === "en-IN" ? "English" : `${l.name}, ${l.english}`;
    b.onclick = () => chooseLanguage(l);
    $("lang-grid").append(b);
  }
})();

// ------------------------------------------------------------------ step 2: show the form
async function chooseLanguage(l) {
  lang = l;
  $("welcome").hidden = true;
  $("start").hidden = false;
  $("instruction").textContent = "";
  try {
    const ins = await api(`/api/instruction?lang=${l.code}`);
    $("instruction").textContent = ins.text;
    if (ins.audio_b64) { $("player").src = `data:audio/wav;base64,${ins.audio_b64}`; $("player").play().catch(() => {}); }
  } catch { /* the English copy on screen still explains the step */ }
}
$("back").onclick = () => { $("player").pause(); $("start").hidden = true; $("welcome").hidden = false; };
$("use-sample").onclick = () => startSample();
$("try-photo").onclick = async () => {
  const blob = await (await fetch("/static/sample-income-form.png")).blob();
  processDoc(new File([blob], "sample-income-form.png", { type: "image/png" }), "form");
};
$("open-camera").onclick = () => openCamera("form");
$("form-file").onchange = (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) processDoc(f, "form"); };

function enterWorkspace() {
  $("player").pause();
  $("welcome").hidden = true;
  $("start").hidden = true;
  $("workspace").hidden = false;
  $("lang-pill").textContent = lang.code === "en-IN" ? "English" : `${lang.name} (${lang.english})`;
  $("stamp-local").textContent = COMPLETE[lang.code] || "";
  $("chat").innerHTML = "";
  $("question").textContent = "";
  wasDone = false;
}

async function startSample() {
  scanUrl = null;
  enterWorkspace();
  setBusy(true, "Getting your form ready");
  try {
    handle(await api("/api/session", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: lang.code }),
    }));
  } catch (e) { addMsg("err", e.message); setBusy(false, "Tap the mic to answer"); }
}

// ------------------------------------------------------------------ camera
let camStream = null;
let camPurpose = "form";

async function openCamera(purpose) {
  camPurpose = purpose;
  $("player").pause();
  $("camera").hidden = false;
  $("camera-msg").textContent = purpose === "id"
    ? "Fit your ID card or marksheet inside the frame" : "Fit the whole page inside the frame";
  $("shutter").disabled = true;
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false,
    });
    $("video").srcObject = camStream;
    await $("video").play();
    $("shutter").disabled = false;
  } catch {
    $("camera-msg").textContent = "The camera is not available here. Use “Upload instead” to choose a photo.";
  }
}

function closeCamera() {
  camStream?.getTracks().forEach((t) => t.stop());
  camStream = null;
  $("video").srcObject = null;
  $("camera").hidden = true;
}

$("camera-cancel").onclick = closeCamera;
$("camera-file").onchange = (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (f) { closeCamera(); processDoc(f, camPurpose); }
};
$("shutter").onclick = () => {
  const v = $("video");
  if (!v.videoWidth) return;
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  c.toBlob((blob) => { closeCamera(); processDoc(new File([blob], "scan.jpg", { type: "image/jpeg" }), camPurpose); },
    "image/jpeg", 0.92);
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("camera").hidden) closeCamera(); });

// ------------------------------------------------------------------ scanning (form or ID)
let scanUrl = null;

async function processDoc(file, purpose) {
  const url = URL.createObjectURL(file);
  const isPdf = file.type === "application/pdf";
  $("scan-img").hidden = isPdf;
  $("scan-pdf").hidden = !isPdf;
  if (!isPdf) $("scan-img").src = url;
  $("scanning").classList.remove("failed");
  $("scan-retry").hidden = true;
  $("scan-text").textContent = purpose === "form"
    ? "Sarvam Vision is reading the blanks on your form" : "Sarvam Vision is reading your document";
  $("scanning").hidden = false;

  const fd = new FormData();
  fd.append("file", file, file.name || "scan.jpg");
  try {
    let r;
    if (purpose === "form") {
      fd.append("lang", lang.code);
      r = await api("/api/form/scan", { method: "POST", body: fd });
      scanUrl = url;
      enterWorkspace();
      $("scanning").hidden = true;
      addMsg("sys", `Found ${r.state.form.fields.length} blanks on your form`);
    } else {
      fd.append("session_id", session.id);
      r = await api("/api/document", { method: "POST", body: fd });
      $("scanning").hidden = true;
    }
    handle(r);
  } catch (e) {
    $("scanning").classList.add("failed");
    $("scan-text").textContent = e.message;
    $("scan-retry").hidden = false;
    $("scan-retry").onclick = () => { $("scanning").hidden = true; if (purpose === "id") setBusy(false, nextPrompt()); };
  }
}
$("id-scan").onclick = () => { if (session && !busy) openCamera("id"); };

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
  $("dept").textContent = state.scanned ? "Read from your photo by Sarvam Vision" : "Department of Social Welfare, Form S-1 (sample)";
  if (state.scanned && scanUrl) {
    const view = document.createElement("a");
    view.href = scanUrl; view.target = "_blank"; view.rel = "noopener"; view.textContent = "View photo";
    $("dept").append(view);
  }
  const firstMissing = state.form.fields.find((f) => f.kind !== "sensitive" && !state.values[f.key]);
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

    if (f.kind === "sensitive") {
      const own = document.createElement("div");
      own.className = "f-own";
      own.textContent = "Write this yourself on the paper form. Sahayak never asks for it.";
      li.append(label, own);
      $("fields").append(li);
      continue;
    }
    if (f.kind === "choice") {
      const box = document.createElement("div");
      box.className = "f-choices" + (changed.includes(f.key) ? " writing" : "");
      for (const o of f.options) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.setAttribute("aria-pressed", String(state.values[f.key] === o));
        btn.innerHTML = `<span class="box"></span><span></span>`;
        btn.lastChild.textContent = o;
        btn.onclick = () => saveEdit(f.key, o);
        box.append(btn);
      }
      li.append(label, box);
      $("fields").append(li);
      continue;
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
  const askable = state.form.fields.filter((f) => f.kind !== "sensitive");
  const total = askable.length;
  const filled = askable.filter((f) => state.values[f.key]).length;
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
  const names = { scan_s: "Scanning", stt_s: "Listening", doc_s: "Reading", llm_s: "Thinking", tts_s: "Voice" };
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

$("print").onclick = () => window.print();

// ------------------------------------------------------------------ status
function setStatus(t) { $("status").textContent = t; }
function setBusy(b, t) {
  busy = b;
  $("mic").disabled = b;
  $("mic").classList.toggle("thinking", b);
  if (t) setStatus(t);
}
