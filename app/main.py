"""GarageVoice app entrypoint.  Run:  uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database.session import init_db
from app.routers import inspection

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="GarageVoice", lifespan=lifespan)
app.include_router(inspection.router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mocks": {"stt": settings.mock_stt, "llm": settings.mock_llm, "tts": settings.mock_tts},
    }


# Frontend (step 7). Mounted last so API routes take precedence.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
