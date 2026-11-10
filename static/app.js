// GarageVoice frontend: record -> 16 kHz mono WAV -> POST -> job card + voice reply.
const MAX_SECONDS = 25;
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
const HKEY = "gv_history";

const LABELS = {
    engine_condition: "Engine",
    clutch_transmission: "Clutch and gearbox",
    brakes_suspension: "Brakes and suspension",
    body_paint_condition: "Body and paint",
    battery_electricals: "Battery and electricals",
};
const ORDER = ["NOT_CHECKED", "OK", "WARNING", "DEFECTIVE"];
const STAMPS = {
    OK: { cls: "ok", text: "OK" },
    WARNING: { cls: "warn", text: "Watch" },
    DEFECTIVE: { cls: "bad", text: "Defect" },
    NOT_CHECKED: { cls: "none", text: "Not checked" },
};
const PHRASES = [
    "KA 01 AB 1234 Swift. Engine theek hai, clutch thoda hard hai, brake pad ghis gaye hain, battery OK hai.",
    "TS 09 ER 4567 Alto. Engine mein noise hai, body pe dent hai, battery weak hai. Baaki sab theek hai.",
    "MH 12 PQ 7788 Baleno. Sirf suspension kharab hai, baaki sab theek hai.",
];
const MOCK_NAMES = { stt: "speech recognition", llm: "backup extractor", tts: "placeholder audio" };

const $ = (id) => document.getElementById(id);
const player = $("player");
let recorder = null, stream = null, chunks = [], timerId = null, startedAt = 0;
let busy = false, muted = false, stepTimer = null;
let current = null; // { id, transcript, card, ts }

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}
function setStatus(msg) { $("status").textContent = msg; }
function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast._id);
    toast._id = setTimeout(() => t.classList.add("hidden"), 6000);
}

// ------------------------------------------------------------ progress steps
function startSteps() {
    const items = [...document.querySelectorAll("#steps li")];
    let i = 0;
    $("steps").classList.remove("hidden");
    const paint = () => items.forEach((li, idx) => {
        li.classList.toggle("done", idx < i);
        li.classList.toggle("active", idx === i);
    });
    paint();
    clearInterval(stepTimer);
    stepTimer = setInterval(() => { if (i < items.length - 1) { i++; paint(); } }, 1500);
}
function stopSteps() {
    clearInterval(stepTimer);
    $("steps").classList.add("hidden");
}

function setBusy(on) {
    const was = busy;
    busy = on;
    const b = $("recBtn");
    b.disabled = on;
    b.classList.toggle("is-busy", on);
    $("recLabel").textContent = on ? "Working..." : "Tap and speak";
    $("textBtn").disabled = on;
    if (on && !was) startSteps();
    if (!on) stopSteps();
    if (on) setStatus("Reading your inspection...");
}

function unlockAudio() {
    player.src = SILENT_WAV;
    player.play().catch(() => { });
}

// ------------------------------------------------------------ recording
async function toggleRecord() {
    if (busy) return;
    if (recorder && recorder.state === "recording") return recorder.stop();
    unlockAudio();
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
    } catch (e) {
        toast("Microphone is blocked. Allow it in the browser's site settings, or type instead.");
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
    setStatus(`Listening... 0:${String(s).padStart(2, "0")} / 0:${MAX_SECONDS}`);
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
        toast("Could not read that recording. Try again, or type instead.");
        setBusy(false);
        setStatus("");
    }
}

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

// ------------------------------------------------------------ API
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
        const data = await res.json();
        current = { id: data.inspection_id, transcript: data.transcript, card: data.card, ts: Date.now() };
        saveHistory();
        showTranscript();
        draw();
        showMockNote(data.used_mocks);
        playAudio(data);
        setStatus("Saved.");
    } catch (e) {
        toast(e.name === "AbortError" ? "The server took too long. Try again." : e.message || "No connection. Check your network and try again.");
        setStatus("");
    } finally {
        clearTimeout(timeout);
        setBusy(false);
        if ($("status").textContent === "Reading your inspection...") setStatus("");
    }
}

function playAudio(data) {
    player.src = `data:${data.audio_mime};base64,${data.audio_base64}`;
    player.muted = muted;
    player.play().catch(() => { });
}

function showMockNote(used) {
    const note = $("mockNote");
    if (used && used.length) {
        note.textContent = "Fallback in use: " + used.map((m) => MOCK_NAMES[m] || m).join(", ") + ".";
        note.classList.remove("hidden");
    } else note.classList.add("hidden");
}

// ------------------------------------------------------------ render
function computeScore(card) {
    const vals = Object.keys(LABELS).map((k) => card[k].status);
    if (vals.every((s) => s === "NOT_CHECKED")) return 0;
    const w = vals.filter((s) => s === "WARNING").length;
    const d = vals.filter((s) => s === "DEFECTIVE").length;
    return Math.max(0, 10 - w - 3 * d);
}

function showTranscript() {
    $("transcript").textContent = current.transcript;
    $("transcriptBox").classList.remove("hidden");
}

function draw() {
    const c = current.card;
    $("vehNo").value = c.vehicle_number;
    $("vehModel").textContent = c.vehicle_model === "UNKNOWN" ? "Model not stated" : c.vehicle_model;
    $("when").textContent = new Date(current.ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

    const rows = $("rows");
    rows.replaceChildren();
    Object.entries(LABELS).forEach(([key, label]) => {
        const item = c[key];
        const s = STAMPS[item.status] || STAMPS.NOT_CHECKED;
        const li = el("li", "part");
        const main = el("div");
        main.append(el("div", "pname", label));
        if (item.notes) main.append(el("p", "pnote", item.notes));
        const chip = el("button", `chip ${s.cls}`, s.text);
        chip.type = "button";
        chip.addEventListener("click", () => {
            const next = ORDER[(ORDER.indexOf(item.status) + 1) % ORDER.length];
            c[key].status = next;
            c.overall_score = computeScore(c);
            saveHistory();
            draw();
        });
        li.append(main, chip);
        rows.append(li);
    });

    const score = c.overall_score;
    $("score").textContent = score;
    const ring = $("ring");
    ring.style.setProperty("--pct", score * 10);
    ring.style.setProperty("--c", score >= 8 ? "var(--ok)" : score >= 5 ? "var(--warn)" : "var(--bad)");
    $("summary").textContent = c.mechanic_summary_hindi;

    const card = $("card");
    const first = card.classList.contains("hidden");
    card.classList.remove("hidden");
    if (first) {
        const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        card.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    }
}

// ------------------------------------------------------------ history (this browser only)
function loadHistory() {
    try { return JSON.parse(localStorage.getItem(HKEY) || "[]"); } catch (_) { return []; }
}
function saveHistory() {
    if (!current) return;
    try {
        const list = loadHistory().filter((h) => h.ts !== current.ts);
        list.unshift(current);
        localStorage.setItem(HKEY, JSON.stringify(list.slice(0, 25)));
    } catch (_) { }
}
function renderHistory() {
    const box = $("histList");
    box.replaceChildren();
    const list = loadHistory();
    if (!list.length) { box.append(el("div", "empty", "No inspections yet.")); return; }
    list.forEach((h) => {
        const b = el("button", "hitem");
        b.type = "button";
        const left = el("div");
        left.append(el("b", "", h.card.vehicle_number));
        left.append(el("small", "", `${h.card.vehicle_model === "UNKNOWN" ? "Model not stated" : h.card.vehicle_model} - ${new Date(h.ts).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`));
        b.append(left, el("span", "hscore", `${h.card.overall_score}/10`));
        b.addEventListener("click", () => {
            current = h;
            showTranscript();
            draw();
            $("mockNote").classList.add("hidden");
            $("drawer").classList.add("hidden");
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
        box.append(b);
    });
}

// ------------------------------------------------------------ share
function shareText() {
    const c = current.card;
    const lines = [`*GarageVoice inspection*`, `Vehicle: ${c.vehicle_number}${c.vehicle_model !== "UNKNOWN" ? " (" + c.vehicle_model + ")" : ""}`];
    Object.entries(LABELS).forEach(([k, label]) => {
        const it = c[k];
        lines.push(`- ${label}: ${STAMPS[it.status].text}${it.notes ? " (" + it.notes + ")" : ""}`);
    });
    lines.push(`Score: ${c.overall_score}/10`);
    return lines.join("\n");
}

// ------------------------------------------------------------ events
$("recBtn").addEventListener("click", toggleRecord);
$("replayBtn").addEventListener("click", () => {
    player.muted = false;
    player.currentTime = 0;
    player.play().catch(() => toast("The browser blocked playback. Tap Play again."));
});
$("muteBtn").addEventListener("click", () => {
    muted = !muted;
    player.muted = muted;
    $("muteBtn").innerHTML = muted ? "&#128263;" : "&#128266;";
    toast(muted ? "Voice reply muted." : "Voice reply on.");
});
$("waBtn").addEventListener("click", () => {
    if (current) window.open("https://wa.me/?text=" + encodeURIComponent(shareText()), "_blank");
});
$("printBtn").addEventListener("click", () => window.print());
$("newBtn").addEventListener("click", () => {
    current = null;
    $("card").classList.add("hidden");
    $("transcriptBox").classList.add("hidden");
    setStatus("");
    window.scrollTo({ top: 0, behavior: "smooth" });
});
$("histBtn").addEventListener("click", () => { renderHistory(); $("drawer").classList.remove("hidden"); });
$("closeHist").addEventListener("click", () => $("drawer").classList.add("hidden"));
$("drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") $("drawer").classList.add("hidden"); });
$("clearHist").addEventListener("click", () => { try { localStorage.removeItem(HKEY); } catch (_) { } renderHistory(); });

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
$("clearBtn").addEventListener("click", () => ($("textIn").value = ""));

PHRASES.forEach((p) => {
    const b = el("button", "qp", p);
    b.type = "button";
    b.addEventListener("click", () => {
        $("textIn").value = p;
        $("slip").open = true;
        $("slip").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("phrases").append(b);
});

$("vehNo").addEventListener("change", async () => {
    const v = $("vehNo").value.trim();
    if (!current || !current.id || v.length < 3) return;
    try {
        const res = await fetch(`/api/v1/inspections/${current.id}/vehicle`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vehicle_number: v }),
        });
        if (!res.ok) throw new Error();
        const out = await res.json();
        current.card.vehicle_number = out.vehicle_number;
        $("vehNo").value = out.vehicle_number;
        saveHistory();
        setStatus("Vehicle number saved.");
    } catch (_) {
        toast("Could not save the vehicle number. Check your connection and try again.");
    }
});