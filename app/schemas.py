"""Pydantic models for the inspection card. Evon output is validated against these."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Status(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    DEFECTIVE = "DEFECTIVE"
    NOT_CHECKED = "NOT_CHECKED"

    @classmethod
    def _missing_(cls, value):
        # Accept "ok", "Warning", "not checked" etc. from the LLM
        if isinstance(value, str):
            key = value.strip().upper().replace(" ", "_").replace("-", "_")
            if key in cls.__members__:
                return cls[key]
        return None


class ComponentStatus(BaseModel):
    status: Status = Status.NOT_CHECKED
    notes: Optional[str] = None


def _unchecked() -> ComponentStatus:
    return ComponentStatus()


class InspectionCard(BaseModel):
    vehicle_number: str = "UNKNOWN"
    vehicle_model: str = "UNKNOWN"
    engine_condition: ComponentStatus = Field(default_factory=_unchecked)
    clutch_transmission: ComponentStatus = Field(default_factory=_unchecked)
    brakes_suspension: ComponentStatus = Field(default_factory=_unchecked)
    body_paint_condition: ComponentStatus = Field(default_factory=_unchecked)
    battery_electricals: ComponentStatus = Field(default_factory=_unchecked)
    overall_score: int = Field(default=0, ge=0, le=10)
    mechanic_summary_hindi: str = "Inspection save ho gaya hai."

    @field_validator("vehicle_number")
    @classmethod
    def _normalize_vehicle_number(cls, v: str) -> str:
        v = (v or "").strip().upper()
        return v or "UNKNOWN"

    @classmethod
    def safe_default(cls) -> "InspectionCard":
        """Fallback card when the LLM output can't be validated."""
        return cls(
            mechanic_summary_hindi="Samajh nahi aaya, dobara bolo ya type karo."
        )
