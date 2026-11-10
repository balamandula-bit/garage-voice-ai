"""Inspection table. The full card is stored as JSON; key fields are columns for querying."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.schemas import InspectionCard


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Inspection(Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_number: Mapped[str] = mapped_column(String(32), index=True)
    overall_score: Mapped[int] = mapped_column(Integer)
    transcript: Mapped[str] = mapped_column(Text, default="")
    card: Mapped[dict] = mapped_column(JSON)
    used_mocks: Mapped[str] = mapped_column(String(32), default="")  # e.g. "stt,llm,tts"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    @classmethod
    def from_card(cls, card: InspectionCard, transcript: str = "", used_mocks: str = "") -> "Inspection":
        return cls(
            vehicle_number=card.vehicle_number,
            overall_score=card.overall_score,
            transcript=transcript,
            card=card.model_dump(mode="json"),
            used_mocks=used_mocks,
        )

    def to_card(self) -> InspectionCard:
        return InspectionCard.model_validate(self.card)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "vehicle_number": self.vehicle_number,
            "overall_score": self.overall_score,
            "transcript": self.transcript,
            "card": self.card,
            "used_mocks": self.used_mocks,
            "created_at": self.created_at.isoformat(),
        }
