"""Thin HTTP layer. All logic lives in services/pipeline.py."""
import base64

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.models import Inspection
from app.database.session import get_db
from app.schemas import InspectionCard
from app.services import pipeline
from app.services.pipeline import NoSpeechError, PipelineResult

router = APIRouter(prefix="/api/v1")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class TextIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class VehicleIn(BaseModel):
    vehicle_number: str = Field(min_length=3, max_length=20)


def _response(r: PipelineResult) -> dict:
    return {
        "inspection_id": r.inspection_id,
        "transcript": r.transcript,
        "language": r.language,
        "card": r.card.model_dump(mode="json"),
        "used_mocks": r.used_mocks,
        "audio_mime": r.audio_mime,
        "audio_base64": base64.b64encode(r.audio).decode(),
    }


@router.post("/inspect-voice")
async def inspect_voice(audio: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty audio upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Audio too large")
    try:
        result = await pipeline.process_audio(data, audio.filename or "audio.webm", audio.content_type, db)
    except NoSpeechError as e:
        raise HTTPException(422, str(e))
    return _response(result)


@router.post("/inspect-text")
async def inspect_text(body: TextIn, db: Session = Depends(get_db)):
    return _response(await pipeline.process_text(body.text, db))


@router.get("/inspections/{vehicle_number}")
def inspection_history(vehicle_number: str, db: Session = Depends(get_db)):
    vn = vehicle_number.strip().upper()
    rows = (
        db.query(Inspection)
        .filter(Inspection.vehicle_number == vn)
        .order_by(Inspection.id.desc())
        .limit(20)
        .all()
    )
    return {"vehicle_number": vn, "count": len(rows), "inspections": [r.to_dict() for r in rows]}


@router.patch("/inspections/{inspection_id}/vehicle")
def correct_vehicle(inspection_id: int, body: VehicleIn, db: Session = Depends(get_db)):
    row = db.get(Inspection, inspection_id)
    if row is None:
        raise HTTPException(404, "Inspection not found")
    card = InspectionCard.model_validate({**row.card, "vehicle_number": body.vehicle_number})  # normalizes
    row.vehicle_number = card.vehicle_number
    row.card = card.model_dump(mode="json")
    db.commit()
    return {"inspection_id": row.id, "vehicle_number": row.vehicle_number}
