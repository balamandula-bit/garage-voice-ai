"""All external-service settings live here. Fix endpoints/fields in this file only."""
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Global mock switch (per-service overrides below) ----
    USE_MOCKS: bool = True
    USE_MOCK_STT: Optional[bool] = None
    USE_MOCK_LLM: Optional[bool] = None
    USE_MOCK_TTS: Optional[bool] = None

    # ---- Gnani (Prisma STT + Timbre TTS), both on api.vachana.ai ----
    GNANI_API_KEY: str = ""
    GNANI_BASE_URL: str = "https://api.vachana.ai"
    GNANI_AUTH_HEADER: str = "X-API-Key-ID"

    # Prisma STT: POST multipart/form-data
    STT_PATH: str = "/stt/v3"
    STT_MODEL: str = "prisma-v3.0"
    STT_LANGUAGE_CODE: str = "hi-IN,en-IN"  # up to 4 codes; hints, not a lock
    STT_FORMAT: str = "transcribe"
    STT_KEYTERMS: str = "clutch,brake,battery,engine,suspension,gearbox,silencer,radiator"
    STT_TOPIC: str = "Indian garage vehicle inspection in Hinglish: engine, clutch, brakes, suspension, body, battery"
    STT_FIELD_AUDIO: str = "audio_file"
    STT_FIELD_TRANSCRIPT: str = "transcript"  # key in JSON response
    STT_MAX_AUDIO_SECONDS: int = 25  # API hard limit is 30
    STT_TIMEOUT: float = 20.0

    # Timbre TTS: POST JSON, response body is raw audio bytes
    TTS_PATH: str = "/api/v1/tts/inference"
    TTS_MODEL: str = "timbre-v2.5"
    TTS_VOICE: str = "Poorvi"  # Hinglish voice
    TTS_LANGUAGE: str = "hi-en"
    TTS_SPEED: float = 1.0
    TTS_SAMPLE_RATE: int = 24000
    TTS_CONTAINER: str = "wav"
    TTS_TIMEOUT: float = 20.0

    # ---- Evon LLM: OpenAI-compatible /v1/chat/completions ----
    # No hosted endpoint found yet. Empty base URL => always mock.
    EVON_BASE_URL: str = ""
    EVON_PATH: str = "/v1/chat/completions"
    EVON_MODEL: str = "gnani/gnani-evon-v3.3-30B-A3B"
    EVON_API_KEY: str = ""
    EVON_TEMPERATURE: float = 0.1
    EVON_MAX_TOKENS: int = 600
    EVON_TIMEOUT: float = 30.0

    # ---- Resilience ----
    RETRIES: int = 1  # one retry per service call
    RETRY_BACKOFF_SECONDS: float = 1.5  # also used for 429 (1 active request limit)

    # ---- Database ----
    DATABASE_URL: str = "sqlite:///./garagevoice.db"

    # ---- Derived helpers ----
    @property
    def mock_stt(self) -> bool:
        if self.USE_MOCK_STT is not None:
            return self.USE_MOCK_STT
        return self.USE_MOCKS or not self.GNANI_API_KEY

    @property
    def mock_tts(self) -> bool:
        if self.USE_MOCK_TTS is not None:
            return self.USE_MOCK_TTS
        return self.USE_MOCKS or not self.GNANI_API_KEY

    @property
    def mock_llm(self) -> bool:
        if self.USE_MOCK_LLM is not None:
            return self.USE_MOCK_LLM
        return self.USE_MOCKS or not self.EVON_BASE_URL

    @property
    def stt_url(self) -> str:
        return self.GNANI_BASE_URL.rstrip("/") + self.STT_PATH

    @property
    def tts_url(self) -> str:
        return self.GNANI_BASE_URL.rstrip("/") + self.TTS_PATH

    @property
    def evon_url(self) -> str:
        return self.EVON_BASE_URL.rstrip("/") + self.EVON_PATH

    def gnani_headers(self) -> dict:
        return {self.GNANI_AUTH_HEADER: self.GNANI_API_KEY}

    def evon_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.EVON_API_KEY:
            h["Authorization"] = f"Bearer {self.EVON_API_KEY}"
        return h

    def tts_audio_config(self) -> dict:
        return {
            "sample_rate": self.TTS_SAMPLE_RATE,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": self.TTS_CONTAINER,
        }


settings = Settings()
