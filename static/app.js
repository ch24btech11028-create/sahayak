// Sahayak: choose a language → scan a paper form → answer by voice → the form fills itself.

const $ = (id) => document.getElementById(id);

const state = {
  lang: null,        // language from /api/config
  session: null,     // latest session state from the server
  busy: false,       // a request or recording is in progress
  recorder: null,    // the current answer being recorded
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
  pauseListening();
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
  listenSoon();
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
  openMic();
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
    $("scan-retry").onclick = () => { $("scanning").hidden = true; listenSoon(); };
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
  else { setBusy(false, nextPrompt()); listenSoon(); }
}

async function sendTurn(fields, label) {
  setBusy(true, label);
  try {
    handleTurn(await api("/api/turn", { method: "POST", body: form({ session_id: state.session.id, ...fields }) }));
  } catch (e) {
    if (!e.message.startsWith("Nothing was heard")) addMessage("err", e.message);
    setBusy(false, nextPrompt());
    listenSoon();
  }
}

$("text-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("text-input").value.trim();
  if (!text || !state.session || state.busy) return;
  $("text-input").value = "";
  pauseListening();
  sendTurn({ text }, "Thinking");
};

const nextPrompt = () => (state.session?.done ? "Your form is complete"
  : state.micBlocked ? "The microphone is blocked. Allow it in the browser, or type your answers"
  : state.listening ? "Listening… speak your answer" : "Listening paused. Tap the mic to continue");

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
  pauseListening();             // never record Sahayak's own voice
  player.src = `data:audio/wav;base64,${b64}`;
  if (isReply) {
    setBusy(false, "Speaking…");
    player.onended = () => { setStatus(nextPrompt()); listenSoon(); };
  }
  player.play().catch(() => {
    if (!isReply) return;
    setStatus("Press “Hear it again” to listen");
    listenSoon();
  });
}
$("replay").onclick = () => state.lastAudio && playAudio(state.lastAudio, true);

// ------------------------------------------------------------------ audio in (hands-free)
// The mic stays open for the whole form. Each answer is cut when the user pauses, sent, and
// listening resumes once Sahayak has finished speaking. The mic button pauses and resumes this.
const RECORDING_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
const MIN_RECORDING_BYTES = 1200;
const VAD = {
  checkMs: 50,
  calibrateMs: 300,        // measure the room's background noise first
  minSpeechMs: 250,        // this much speech counts as the user talking
  endSilenceMs: 1300,      // pause that ends an answer
  maxAnswerMs: 25000,      // stay under the 30 s speech-to-text limit
  restartAfterMs: 15000,   // nothing said: start a fresh recording
};
const mic = { stream: null, analyser: null, buffer: null };
state.listening = true;    // hands-free is on unless the user pauses it

async function openMic() {
  if (mic.stream) return true;
  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const ctx = new AudioContext();
    await ctx.resume();
    mic.analyser = ctx.createAnalyser();
    mic.analyser.fftSize = 1024;
    ctx.createMediaStreamSource(mic.stream).connect(mic.analyser);
    mic.buffer = new Float32Array(mic.analyser.fftSize);
    return true;
  } catch {
    state.listening = false;
    state.micBlocked = true;
    updateMicButton();
    setStatus(nextPrompt());
    return false;
  }
}

function micLevel() {
  mic.analyser.getFloatTimeDomainData(mic.buffer);
  let sum = 0;
  for (const v of mic.buffer) sum += v * v;
  return Math.sqrt(sum / mic.buffer.length);
}

const listenSoon = () => setTimeout(listen, 200);

async function listen() {
  const s = state.session;
  if (!state.listening || state.busy || state.recorder || !s || s.done) return;
  if (!$("player").paused || !$("camera").hidden || !$("scanning").hidden) return;
  if (!(await openMic()) || state.recorder) return;

  const mimeType = RECORDING_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
  const recorder = new MediaRecorder(mic.stream, mimeType ? { mimeType } : {});
  const chunks = [];
  let elapsed = 0, speech = 0, silence = 0, spoke = false;
  const calibration = [];
  let threshold = null;

  state.recorder = recorder;
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    clearInterval(timer);
    state.recorder = null;
    updateMicButton();
    if (recorder.discard || !spoke) return listenSoon();
    sendRecording(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
  };
  recorder.start(250);
  updateMicButton();
  setStatus("Listening… speak your answer");

  const timer = setInterval(() => {
    const level = micLevel();
    elapsed += VAD.checkMs;
    if (threshold === null) {
      calibration.push(level);
      if (elapsed < VAD.calibrateMs) return;
      const noise = calibration.reduce((a, b) => a + b, 0) / calibration.length;
      threshold = Math.min(0.05, Math.max(0.012, noise * 2.5));
    }
    $("mic").style.setProperty("--level", Math.min(1, level / (threshold * 4)).toFixed(2));
    if (level > threshold) {
      speech += VAD.checkMs;
      silence = 0;
      if (!spoke && speech >= VAD.minSpeechMs) { spoke = true; setStatus("Listening… I'll reply when you pause"); }
    } else {
      silence += VAD.checkMs;
      if (!spoke) speech = Math.max(0, speech - VAD.checkMs);
    }
    if ((spoke && silence >= VAD.endSilenceMs) || elapsed >= VAD.maxAnswerMs) recorder.stop();
    else if (!spoke && elapsed >= VAD.restartAfterMs) { recorder.discard = true; recorder.stop(); }
  }, VAD.checkMs);
}

// Stop the current recording without sending it (Sahayak is about to speak, or the user typed).
function pauseListening() {
  if (state.recorder) { state.recorder.discard = true; state.recorder.stop(); }
}

function sendRecording(blob) {
  if (blob.size < MIN_RECORDING_BYTES) return listenSoon();
  const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
  sendTurn({ audio: new File([blob], `speech.${ext}`, { type: blob.type }) }, "Understanding your answer");
}

function updateMicButton() {
  const recording = Boolean(state.recorder);
  $("mic").classList.toggle("rec", recording);
  $("mic").classList.toggle("paused", !state.listening);
  $("mic").setAttribute("aria-label", state.listening ? "Pause listening" : "Resume listening");
  if (!recording) $("mic").style.removeProperty("--level");
}

$("mic").onclick = () => {
  state.micBlocked = false;   // let the user retry after allowing the mic
  state.listening = !state.listening;
  updateMicButton();
  if (state.listening) { setStatus("Listening… speak your answer"); listen(); }
  else { pauseListening(); setStatus("Listening paused. Tap the mic to continue"); }
};

// ------------------------------------------------------------------ status line
function setStatus(text) { $("status").textContent = text; }
function setBusy(busy, text) {
  state.busy = busy;
  $("mic").disabled = busy;
  $("mic").classList.toggle("thinking", busy);
  if (text) setStatus(text);
}
