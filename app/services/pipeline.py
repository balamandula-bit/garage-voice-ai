"""Orchestration: audio -> STT -> LLM -> save -> TTS.
Calls run one after another on purpose (Gnani allows 1 active request per account).
Each service wrapper handles its own retry and mock fallback, so the demo never dies."""
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.database.models import Inspection
from app.schemas import InspectionCard
from app.services.evon_llm import extract_card_or_mock
from app.services.prisma_stt import transcribe_or_mock
from app.services.timbre_tts import synthesize_or_mock

log = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class NoSpeechError(PipelineError):
    pass


@dataclass
class PipelineResult:
    inspection_id: int
    transcript: str
    card: InspectionCard
    audio: bytes
    audio_mime: str
    used_mocks: list[str]
    language: Optional[str] = None


async def process_audio(
    audio: bytes, filename: str, content_type: Optional[str], db: Session
) -> PipelineResult:
    stt = await transcribe_or_mock(audio, filename, content_type)
    if not stt.transcript.strip():
        raise NoSpeechError("Kuch sunai nahi diya. Dobara bolo ya type karo.")
    mocks = ["stt"] if stt.mocked else []
    log.info("STT (%s): %s", "mock" if stt.mocked else stt.model, stt.transcript)
    return await _finish(stt.transcript, mocks, db, stt.language)


async def process_text(text: str, db: Session) -> PipelineResult:
    return await _finish(text.strip(), [], db, None)


async def _finish(transcript: str, mocks: list[str], db: Session, language: Optional[str]) -> PipelineResult:
    llm = await extract_card_or_mock(transcript)
    if llm.mocked:
        mocks.append("llm")
    card = llm.card

    row = Inspection.from_card(card, transcript, ",".join(mocks))
    db.add(row)
    db.commit()
    db.refresh(row)

    tts = await synthesize_or_mock(card.mechanic_summary_hindi)
    if tts.mocked:
        mocks.append("tts")
        row.used_mocks = ",".join(mocks)
        db.commit()

    return PipelineResult(
        inspection_id=row.id,
        transcript=transcript,
        card=card,
        audio=tts.audio,
        audio_mime=tts.content_type,
        used_mocks=mocks,
        language=language,
    )
