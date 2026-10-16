// Sahayak: choose a language → scan a paper form → answer by voice → the form fills itself.

const $ = (id) => document.getElementById(id);

const state = {
  lang: null,        // language from /api/config
  session: null,     // latest session state from the server
  busy: false,       // a request or recording is in progress
  recorder: null,
  chunks: [],
  camera: null,      // { stream, purpose: "form" | "id" }
  lastAudio: null,
  scanUrl: null,     // object URL of the scanned photo, for "View photo"
  wasDone: false,
};

const SAMPLE_PHOTO = "/static/sample-income-form.png";
const STAGE_NAMES = { scan_s: "Scanning", doc_s: "Reading", stt_s: "Listening", llm_s: "Thinking", tts_s: "Voice" };

// ------------------------------------------------------------------ helpers
async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function form(fields) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  return fd;
}

function show(screen) {
  for (const id of ["welcome", "start", "workspace"]) $(id).hidden = id !== screen;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

const languageLabel = (l) => (l.code === "en-IN" ? "English" : `${l.name} (${l.english})`);

// ------------------------------------------------------------------ 1. choose a language
(async function boot() {
  const { languages } = await api("/api/config");
  for (const l of languages) {
    const b = el("button");
    b.setAttribute("role", "listitem");
    b.append(el("span", "speak", l.speak), el("span", "lname", l.code === "en-IN" ? "English" : `${l.name}, ${l.english}`));
    b.onclick = () => chooseLanguage(l);
    $("lang-grid").append(b);
  }
})();

async function chooseLanguage(l) {
  state.lang = l;
  show("start");
  $("instruction").textContent = "";
  try {
    const { text, audio_b64 } = await api(`/api/instruction?lang=${l.code}`);
    $("instruction").textContent = text;
    if (audio_b64) playAudio(audio_b64);
  } catch { /* the English text on screen still explains the step */ }
}

// ------------------------------------------------------------------ 2. show the form (camera, upload, sample)
$("back").onclick = () => { $("player").pause(); show("welcome"); };
$("open-camera").onclick = () => openCamera("form");
$("id-scan").onclick = () => { if (state.session && !state.busy) openCamera("id"); };
$("form-file").onchange = (e) => takeFile(e, "form");
$("camera-file").onchange = (e) => { closeCamera(); takeFile(e, state.camera?.purpose || "form"); };
$("try-photo").onclick = async () => {
  const blob = await (await fetch(SAMPLE_PHOTO)).blob();
  scan(new File([blob], "sample-income-form.png", { type: "image/png" }), "form");
};

function takeFile(event, purpose) {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) scan(file, purpose);
}

async function openCamera(purpose) {
  $("player").pause();
  $("camera").hidden = false;
  $("shutter").disabled = true;
  $("camera-msg").textContent = purpose === "id"
    ? "Fit your ID card or marksheet inside the frame" : "Fit the whole page inside the frame";
  state.camera = { stream: null, purpose };
  try {
    state.camera.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } },
    });
    $("video").srcObject = state.camera.stream;
    await $("video").play();
    $("shutter").disabled = false;
  } catch {
    $("camera-msg").textContent = "The camera is not available here. Use “Upload instead” to choose a photo.";
  }
}

function closeCamera() {
  state.camera?.stream?.getTracks().forEach((t) => t.stop());
  $("video").srcObject = null;
  $("camera").hidden = true;
}

$("camera-cancel").onclick = closeCamera;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("camera").hidden) closeCamera(); });
$("shutter").onclick = () => {
  const video = $("video");
  if (!video.videoWidth) return;
  const canvas = el("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  const purpose = state.camera.purpose;
  canvas.toBlob((blob) => { closeCamera(); scan(new File([blob], "scan.jpg", { type: "image/jpeg" }), purpose); },
    "image/jpeg", 0.92);
};

// Send a photo to Sarvam Vision: a form starts a new session, an ID pre-fills the open one.
async function scan(file, purpose) {
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

  try {
    if (purpose === "form") {
      const result = await api("/api/form/scan", { method: "POST", body: form({ lang: state.lang.code, file }) });
      state.scanUrl = url;
      openWorkspace();
      addMessage("sys", `Found ${result.state.form.fields.length} blanks on your form`);
      $("scanning").hidden = true;
      handleTurn(result);
    } else {
      const result = await api("/api/document", { method: "POST", body: form({ session_id: state.session.id, file }) });
      $("scanning").hidden = true;
      handleTurn(result);
    }
  } catch (e) {
    $("scanning").classList.add("failed");
    $("scan-text").textContent = e.message;
    $("scan-retry").hidden = false;
    $("scan-retry").onclick = () => { $("scanning").hidden = true; };
  }
}

// ------------------------------------------------------------------ 3. the conversation
function openWorkspace() {
  $("player").pause();
  show("workspace");
  $("lang-pill").textContent = languageLabel(state.lang);
  $("stamp-local").textContent = state.lang.complete;
  $("chat").replaceChildren();
  $("question").textContent = "";
  state.wasDone = false;
}
$("restart").onclick = () => location.reload();

function addMessage(kind, text) {
  $("chat").append(el("li", kind, text));
  $("chat").scrollTop = $("chat").scrollHeight;
}

function handleTurn(r) {
  // The previous question moves into the history; the new one takes the big slot.
  if ($("question").textContent) addMessage("bot", $("question").textContent);
  if (r.heard) addMessage("user", r.heard);
  if (r.error) addMessage("err", r.error);
  $("question").textContent = r.reply;
  $("question").classList.toggle("long", r.reply.length > 110);

  renderForm(r.state, r.changed);
  $("timings").textContent = Object.entries(STAGE_NAMES)
    .filter(([key]) => r.timings[key] != null)
    .map(([key, name]) => `${name} ${r.timings[key]}s`).join(", ");

  state.lastAudio = r.audio_b64;
  $("replay").hidden = !r.audio_b64;
  if (r.audio_b64) playAudio(r.audio_b64, true);
  else setBusy(false, nextPrompt());
}

async function sendTurn(fields, label) {
  setBusy(true, label);
  try {
    handleTurn(await api("/api/turn", { method: "POST", body: form({ session_id: state.session.id, ...fields }) }));
  } catch (e) {
    addMessage("err", e.message);
    setBusy(false, nextPrompt());
  }
}

$("text-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !state.session || state.busy) return;
  $("text-input").value = "";
  sendTurn({ text }, "Thinking");
};

const nextPrompt = () => (state.session?.done ? "Your form is complete" : "Tap the mic to answer");

// ------------------------------------------------------------------ the form on the right
function renderForm(session, changed = []) {
  state.session = session;
  $("form-title").textContent = session.form.title;
  $("dept").replaceChildren("Read from your photo by Sarvam Vision");
  if (state.scanUrl) {
    const view = el("a", null, "View photo");
    Object.assign(view, { href: state.scanUrl, target: "_blank", rel: "noopener" });
    $("dept").append(view);
  }

  const askable = session.form.fields.filter((f) => f.kind !== "sensitive");
  const current = !session.done && askable.find((f) => !session.values[f.key]);
  $("fields").replaceChildren(...session.form.fields.map((f) => fieldRow(f, session, changed, f === current)));

  const filled = askable.filter((f) => session.values[f.key]).length;
  $("progress-text").innerHTML = `<b>${filled}/${askable.length}</b>answered`;

  $("stamp").hidden = !session.done;
  $("print").hidden = !session.done;
  if (session.done && !state.wasDone) {
    $("stamp").classList.remove("land");
    void $("stamp").offsetWidth; // restart the stamp animation
    $("stamp").classList.add("land");
  }
  state.wasDone = session.done;
}

function fieldRow(f, session, changed, isCurrent) {
  const li = el("li", isCurrent ? "current" : null);
  const label = el("div", "f-label", f.label);
  if (f.local_label && f.local_label !== f.label) label.append(el("span", "local", f.local_label));
  if (!session.done) {
    const remove = el("button", "f-remove", "Not on my form");
    remove.type = "button";
    remove.onclick = () => removeField(f.key);
    label.append(remove);
  }
  li.append(label);

  const value = session.values[f.key] || "";
  const justWritten = changed.includes(f.key);

  if (f.kind === "sensitive") {
    li.append(el("div", "f-own", "Write this yourself on the paper form. Sahayak never asks for it."));
  } else if (f.kind === "choice") {
    const choices = el("div", "f-choices" + (justWritten ? " writing" : ""));
    for (const option of f.options) {
      const b = el("button");
      b.type = "button";
      b.setAttribute("aria-pressed", String(value === option));
      b.append(el("span", "box"), el("span", null, option));
      b.onclick = () => saveEdit(f.key, option);
      choices.append(b);
    }
    li.append(choices);
  } else {
    const input = el("div", "f-value" + (justWritten && value ? " writing" : ""), value);
    Object.assign(input, { contentEditable: "true", spellcheck: false });
    input.dataset.hint = f.hint;
    input.setAttribute("aria-label", f.label);
    input.onblur = () => saveEdit(f.key, input.textContent);
    input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); input.blur(); } };
    li.append(input);
  }
  return li;
}

async function saveEdit(field, value) {
  if ((state.session.values[field] || "") === value.trim()) return;
  try {
    renderForm(await api(`/api/session/${state.session.id}/field`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ field, value }),
    }), [field]);
  } catch (e) { addMessage("err", e.message); }
}

async function removeField(key) {
  try {
    renderForm(await api(`/api/session/${state.session.id}/field/${encodeURIComponent(key)}`, { method: "DELETE" }));
  } catch (e) { addMessage("err", e.message); }
}

$("print").onclick = () => window.print();

// ------------------------------------------------------------------ audio out
function playAudio(b64, isReply = false) {
  const player = $("player");
  player.src = `data:audio/wav;base64,${b64}`;
  if (isReply) {
    setBusy(false, "Speaking. Tap the mic to interrupt");
    player.onended = () => setStatus(nextPrompt());
  }
  player.play().catch(() => isReply && setStatus("Press “Hear it again” to listen"));
}
$("replay").onclick = () => state.lastAudio && playAudio(state.lastAudio, true);

// ------------------------------------------------------------------ audio in (push-to-talk)
const RECORDING_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
const MIN_RECORDING_BYTES = 1200;

async function startRecording() {
  if (state.busy || state.recorder || !state.session) return;
  $("player").pause(); // barge-in: stop Sahayak talking
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = RECORDING_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    state.recorder = recorder;
    state.chunks = [];
    recorder.ondataavailable = (e) => e.data.size && state.chunks.push(e.data);
    recorder.onstop = () => { stream.getTracks().forEach((t) => t.stop()); sendRecording(recorder.mimeType); };
    recorder.start();
    $("mic").classList.add("rec");
    $("mic").setAttribute("aria-label", "Tap to finish");
    setStatus("Listening. Tap again when you finish");
  } catch {
    addMessage("err", "The microphone is blocked. Allow microphone access in the browser, or type your answer.");
  }
}

function stopRecording() {
  if (!state.recorder) return;
  $("mic").classList.remove("rec");
  $("mic").setAttribute("aria-label", "Tap to answer");
  state.recorder.stop();
}

function sendRecording(mimeType) {
  state.recorder = null;
  const blob = new Blob(state.chunks, { type: mimeType || "audio/webm" });
  if (blob.size < MIN_RECORDING_BYTES) return setStatus("That was too short. Tap and speak again");
  const ext = mimeType.includes("mp4") ? "m4a" : mimeType.includes("ogg") ? "ogg" : "webm";
  sendTurn({ audio: new File([blob], `speech.${ext}`, { type: blob.type }) }, "Understanding your answer");
}

$("mic").onclick = () => (state.recorder ? stopRecording() : startRecording());

// Hold Space to talk, but only when nothing else has focus, so typing never opens the mic.
const spaceToTalk = (e) => e.code === "Space" && [document.body, $("mic")].includes(document.activeElement);
document.addEventListener("keydown", (e) => { if (spaceToTalk(e) && !e.repeat) { e.preventDefault(); startRecording(); } });
document.addEventListener("keyup", (e) => { if (spaceToTalk(e)) { e.preventDefault(); stopRecording(); } });

// ------------------------------------------------------------------ status line
function setStatus(text) { $("status").textContent = text; }
function setBusy(busy, text) {
  state.busy = busy;
  $("mic").disabled = busy;
  $("mic").classList.toggle("thinking", busy);
  if (text) setStatus(text);
}
