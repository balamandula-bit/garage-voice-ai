// GarageVoice frontend: record -> convert to 16 kHz mono WAV -> POST -> render job card + play audio.
const MAX_SECONDS = 25; // Prisma REST limit is 30 s
const SAMPLE_TEXT = "KA 01 AB 1234 Swift. Engine theek hai, clutch thoda hard hai, brake pad ghis gaye hain, battery OK hai.";
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

const LABELS = {
    engine_condition: "Engine",
    clutch_transmission: "Clutch and gearbox",
    brakes_suspension: "Brakes and suspension",
    body_paint_condition: "Body and paint",
    battery_electricals: "Battery and electricals",
};
const STAMPS = {
    OK: { cls: "ok", text: "OK" },
    WARNING: { cls: "watch", text: "Watch" },
    DEFECTIVE: { cls: "defect", text: "Defect" },
    NOT_CHECKED: { cls: "none", text: "Not checked" },
};
const MOCK_NAMES = {
    stt: "speech recognition",
    llm: "rule-based extractor (Evon unavailable)",
    tts: "placeholder audio",
};

const $ = (id) => document.getElementById(id);
const player = $("player");
let recorder = null, stream = null, chunks = [], timerId = null, startedAt = 0, busy = false, currentId = null;

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

function setStatus(msg) {
    $("status").textContent = msg;
}

function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._id);
    toast._id = setTimeout(() => t.classList.add("hidden"), 6000);
}

function setBusy(on) {
    busy = on;
    const b = $("recBtn");
    b.disabled = on;
    b.classList.toggle("is-busy", on);
    $("recLabel").textContent = on ? "Working…" : "Tap and speak";
    $("textBtn").disabled = on;
    if (on) setStatus("Reading your inspection…");
}

// Mobile browsers only allow audio.play() after a user gesture: unlock on the first tap.
function unlockAudio() {
    player.src = SILENT_WAV;
    player.play().catch(() => { });
}

// ---------------------------------------------------------------- recording
async function toggleRecord() {
    if (busy) return;
    if (recorder && recorder.state === "recording") return recorder.stop();
    unlockAudio();
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
    } catch (e) {
        toast("The microphone is blocked. Allow it in the browser's site settings, or type below.");
        return;
    }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = onRecorded;
    recorder.start();
    startedAt = Date.now();
    $("recBtn").classList.add("is-recording");
    $("recLabel").textContent = "Tap to stop";
    timerId = setInterval(tick, 250);
    tick();
}

function tick() {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    setStatus(`Listening… 0:${String(s).padStart(2, "0")}`);
    if (s >= MAX_SECONDS && recorder && recorder.state === "recording") recorder.stop();
}

async function onRecorded() {
    clearInterval(timerId);
    stream.getTracks().forEach((t) => t.stop());
    $("recBtn").classList.remove("is-recording");
    $("recLabel").textContent = "Tap and speak";
    if (Date.now() - startedAt < 700) {
        setStatus("That was too short. Tap and speak again.");
        return;
    }
    setBusy(true);
    try {
        const wav = await blobToWav(new Blob(chunks, { type: recorder.mimeType }));
        const fd = new FormData();
        fd.append("audio", wav, "recording.wav");
        await submit("/api/v1/inspect-voice", { method: "POST", body: fd });
    } catch (e) {
        toast("Could not read that recording. Try again, or type below.");
        setBusy(false);
        setStatus("");
    }
}

// Decode whatever the browser recorded (webm/mp4), resample to 16 kHz mono, write a WAV.
async function blobToWav(blob) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    ctx.close();
    const rate = 16000;
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), rate);
}

function encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, samples.length * 2, true);
    let o = 44;
    for (const s of samples) {
        const x = Math.max(-1, Math.min(1, s));
        v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7fff, true);
        o += 2;
    }
    return new Blob([buf], { type: "audio/wav" });
}

// ---------------------------------------------------------------- API
async function submit(url, opts) {
    setBusy(true);
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 60000);
    try {
        const res = await fetch(url, { ...opts, signal: ctrl.signal });
        if (!res.ok) {
            let msg = "Something went wrong on the server. Try again.";
            try {
                const j = await res.json();
                if (typeof j.detail === "string") msg = j.detail;
            } catch (_) { }
            throw new Error(msg);
        }
        render(await res.json());
        setStatus("Saved.");
    } catch (e) {
        toast(e.name === "AbortError" ? "The server took too long. Try again." : e.message || "No connection. Check your network and try again.");
        setStatus("");
    } finally {
        clearTimeout(timeout);
        setBusy(false);
        if ($("status").textContent === "Reading your inspection…") setStatus("");
    }
}

// ---------------------------------------------------------------- render
function render(data) {
    $("transcript").textContent = data.transcript;
    $("transcriptBox").classList.remove("hidden");

    const c = data.card;
    currentId = data.inspection_id;
    $("vehNo").value = c.vehicle_number;
    $("vehModel").textContent = c.vehicle_model === "UNKNOWN" ? "Model not stated" : c.vehicle_model;

    const score = $("score");
    score.textContent = `${c.overall_score}/10`;
    score.dataset.level = c.overall_score >= 8 ? "good" : c.overall_score >= 5 ? "mid" : "low";

    const rows = $("rows");
    rows.replaceChildren();
    Object.entries(LABELS).forEach(([key, label], i) => {
        const item = c[key];
        const s = STAMPS[item.status] || STAMPS.NOT_CHECKED;
        const li = el("li", "part");
        const main = el("div", "part-main");
        main.append(el("div", "part-name", label));
        if (item.notes) main.append(el("p", "part-note", item.notes));
        const stamp = el("div", `stamp ${s.cls}`, s.text);
        stamp.style.setProperty("--i", i);
        li.append(main, stamp);
        rows.append(li);
    });
    $("summary").textContent = c.mechanic_summary_hindi;

    const note = $("mockNote");
    if (data.used_mocks.length) {
        note.textContent = "Fallback in use: " + data.used_mocks.map((m) => MOCK_NAMES[m] || m).join(", ") + ".";
        note.classList.remove("hidden");
    } else {
        note.classList.add("hidden");
    }

    const card = $("card");
    card.classList.remove("hidden");
    card.classList.remove("stamping");
    void card.offsetWidth; // restart the stamp animation
    card.classList.add("stamping");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });

    player.src = `data:${data.audio_mime};base64,${data.audio_base64}`;
    player.play().catch(() => { }); // if blocked, "Play again" works
}

// ---------------------------------------------------------------- events
$("recBtn").addEventListener("click", toggleRecord);
$("replayBtn").addEventListener("click", () => {
    player.currentTime = 0;
    player.play().catch(() => toast("The browser blocked playback. Tap Play again."));
});
$("sampleBtn").addEventListener("click", () => ($("textIn").value = SAMPLE_TEXT));
$("textBtn").addEventListener("click", () => {
    const text = $("textIn").value.trim();
    if (text.length < 2) return toast("Type something first.");
    unlockAudio();
    submit("/api/v1/inspect-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
    });
});
$("vehNo").addEventListener("change", async () => {
    const v = $("vehNo").value.trim();
    if (!currentId || v.length < 3) return;
    try {
        const res = await fetch(`/api/v1/inspections/${currentId}/vehicle`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vehicle_number: v }),
        });
        if (!res.ok) throw new Error();
        $("vehNo").value = (await res.json()).vehicle_number;
        setStatus("Vehicle number saved.");
    } catch (_) {
        toast("Could not save the vehicle number. Check your connection and try again.");
    }
});