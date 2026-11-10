# GarageVoice

**Hands-free vehicle inspection for Indian garages. Speak in Hinglish, get a structured job card and a spoken summary back.**

Mechanics work with greasy hands and no time for forms. GarageVoice lets them describe a vehicle out loud ("KA 01 AB 1234 Swift. Engine theek hai, clutch thoda hard hai, brake pad ghis gaye hain") and turns it into a clean inspection card with a health score, then reads the summary back in a Hinglish voice.

Built for the Gnani.ai internship using Gnani's **Prisma** (speech-to-text) and **Timbre** (text-to-speech) APIs, plus an **Evon** LLM for structured extraction.

## Live

- Live app: _add your Render URL here_

<!-- Add a screenshot or GIF here:
![GarageVoice screenshot](docs/screenshot.png)
-->

## How it works

```
Mic recording (browser, 16 kHz mono WAV)
        |
        v
Prisma STT  ->  Hinglish transcript
        |
        v
Evon LLM    ->  JSON inspection card (validated with Pydantic)
        |
        v
SQLite      ->  inspection saved
        |
        v
Timbre TTS  ->  spoken Hinglish summary (WAV)
        |
        v
Browser     ->  job card + voice reply
```

1. The browser records audio and converts it to 16 kHz mono WAV.
2. The backend sends it to **Prisma STT**, tuned for garage vocabulary (clutch, brake, battery, suspension and so on).
3. The transcript goes to **Evon**, which returns a JSON card covering five components, an overall score out of 10 and a one-line Hindi/Hinglish summary.
4. The card is validated, saved to the database and sent to **Timbre TTS**, which speaks the summary back.

## Features

- Voice input in Hinglish (Hindi + English), with a type-instead option
- Structured inspection card: engine, clutch and gearbox, brakes and suspension, body and paint, battery and electricals
- Status per component: `OK`, `WARNING`, `DEFECTIVE`, `NOT_CHECKED`, with short notes
- Automatic score: 10 minus 1 per warning, minus 3 per defect
- Spoken summary of the result
- Tap a status chip to correct it; the score recalculates
- Edit the vehicle number; the correction is saved to the database
- Inspection history (per browser and per vehicle number via the API)
- Share the card on WhatsApp, or print it
- **Never crashes mid-demo:** every service (STT, LLM, TTS) retries once, then falls back to a mock if the API is down or unconfigured. The UI shows a note when a fallback is in use.

## Tech stack

| Layer | Tools |
| --- | --- |
| Backend | Python, FastAPI, Uvicorn |
| Data | SQLAlchemy, SQLite, Pydantic |
| Speech to text | Gnani Prisma (`prisma-v3.0`) |
| Language model | Evon (OpenAI-compatible `/v1/chat/completions`) |
| Text to speech | Gnani Timbre (`timbre-v2.5`) |
| Frontend | Vanilla HTML, CSS and JavaScript |
| HTTP client | httpx |

## Project structure

```
.
├── app/
│   ├── main.py                 # FastAPI entrypoint, serves the frontend
│   ├── config.py               # All service settings and mock switches
│   ├── prompts.py              # Evon system prompt + Hinglish few-shot examples
│   ├── schemas.py              # Pydantic models for the inspection card
│   ├── database/
│   │   ├── models.py           # Inspection table
│   │   └── session.py          # Engine, session, table creation
│   ├── routers/
│   │   └── inspection.py       # HTTP endpoints
│   └── services/
│       ├── __init__.py         # Shared service exceptions
│       ├── pipeline.py         # STT -> LLM -> save -> TTS orchestration
│       ├── prisma_stt.py       # Prisma STT wrapper + mock
│       ├── evon_llm.py         # Evon LLM wrapper + rule-based mock
│       └── timbre_tts.py       # Timbre TTS wrapper + mock
├── static/
│   ├── index.html
│   └── app.js                  # Recording, WAV encoding, UI
└── README.md
```

## Getting started

### 1. Clone and install

```bash
git clone https://github.com/balamandula-bit/garage-voice-ai.git
cd garage-voice-ai
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root (it is git-ignored, never commit it):

```env
# Set to false to use the real APIs
USE_MOCKS=false

# Gnani (Prisma STT + Timbre TTS)
GNANI_API_KEY=your_gnani_key

# Evon LLM (any OpenAI-compatible endpoint)
EVON_BASE_URL=https://your-evon-endpoint
EVON_API_KEY=your_evon_key
```

With `USE_MOCKS=true` (the default) or no keys set, the app runs entirely on mocks, so you can try it with no API access at all.

You can also switch services individually with `USE_MOCK_STT`, `USE_MOCK_LLM` and `USE_MOCK_TTS`. All other endpoints, models, voices and timeouts are in `app/config.py`.

### 3. Run

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000. Check `http://localhost:8000/health` to see which services are running on mocks.

## API

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/v1/inspect-voice` | Upload audio (`audio` form field), returns transcript, card and spoken reply |
| `POST` | `/api/v1/inspect-text` | JSON `{"text": "..."}`, same response without the STT step |
| `GET` | `/api/v1/inspections/{vehicle_number}` | Last 20 inspections for a vehicle |
| `PATCH` | `/api/v1/inspections/{id}/vehicle` | Correct the vehicle number of a saved inspection |
| `GET` | `/health` | Service status and mock flags |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/inspect-text \
  -H "Content-Type: application/json" \
  -d '{"text": "KA 01 AB 1234 Swift. Engine theek hai, clutch thoda hard hai, brake pad ghis gaye hain."}'
```

Response (trimmed):

```json
{
  "inspection_id": 1,
  "transcript": "KA 01 AB 1234 Swift. Engine theek hai, ...",
  "card": {
    "vehicle_number": "KA-01-AB-1234",
    "vehicle_model": "Swift",
    "engine_condition": { "status": "OK", "notes": null },
    "clutch_transmission": { "status": "WARNING", "notes": "clutch thoda hard" },
    "brakes_suspension": { "status": "DEFECTIVE", "notes": "brake pads ghis gaye" },
    "overall_score": 6,
    "mechanic_summary_hindi": "Swift check ho gayi: ..."
  },
  "used_mocks": [],
  "audio_mime": "audio/wav",
  "audio_base64": "..."
}
```

## Testing each service on its own

Each wrapper can be run standalone:

```bash
python -m app.services.prisma_stt path/to/audio.wav --real
python -m app.services.evon_llm "KA 01 AB 1234 Swift engine theek hai" --real
python -m app.services.timbre_tts "Swift check ho gayi" --real --out out.wav
```

Leave off `--real` to test the mock path.

## Design decisions

- **Sequential calls.** Gnani allows one active request per account, so the pipeline runs STT, LLM and TTS one after another and backs off on HTTP 429.
- **Validated LLM output.** Evon's reply is parsed and checked against Pydantic models. If validation fails, the model gets one retry with the error message, then a safe default card is returned.
- **Tolerant parsing.** Status values like "ok" or "not checked" are normalized, vehicle numbers are uppercased, and spoken digits ("zero one") are handled.
- **Prompting for Hinglish.** The system prompt includes few-shot examples with noisy transcripts and misheard part names, and only marks what the mechanic actually said (everything else stays `NOT_CHECKED`).
- **Spoken numbers.** Scores from 0 to 10 are spelled out before TTS so they are pronounced correctly.

## Deploying on Render

1. Push the repo to GitHub.
2. Create a **Web Service** on Render and connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add your environment variables (`USE_MOCKS`, `GNANI_API_KEY`, `EVON_BASE_URL`, `EVON_API_KEY`) under **Environment**.

Note: the default SQLite file lives on the instance disk and resets on redeploy unless you attach a persistent disk or set `DATABASE_URL` to a hosted database. Browsers also need HTTPS for microphone access, which Render provides.

## Roadmap

- Support more Indian languages
- Per-garage accounts and a shared inspection history
- PDF job card export
- Photo attachments for defects

## Acknowledgements

Built during an internship at [Gnani.ai](https://www.gnani.ai), using the Prisma and Timbre APIs.
