"""Timbre TTS wrapper (Gnani). Real call with timeout + one retry, plus mock fallback.

Standalone test:  python -m app.services.timbre_tts ["text"] [--real] [--out path.wav]
"""
import argparse
import asyncio
import io
import logging
import math
import re
import struct
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.services import (
    ServiceAuthError,
    ServiceBadRequest,
    ServiceError,
    ServiceTimeout,
    ServiceUnavailable,
)

log = logging.getLogger(__name__)
SERVICE = "timbre_tts"

SAMPLE = "Swift check ho gayi: engine theek hai, brake mein dikkat hai. Score 9 out of 10."
_NUM_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]


@dataclass
class TTSResult:
    audio: bytes
    content_type: str = "audio/wav"
    mocked: bool = False


def spell_small_numbers(text: str) -> str:
    """Timbre docs advise spoken words for numbers; spell 0-10 so scores are pronounced right."""
    return re.sub(
        r"\b(\d{1,2})\b",
        lambda m: _NUM_WORDS[int(m.group(1))] if int(m.group(1)) <= 10 else m.group(1),
        text,
    )


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or "no response body"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return f"{err.get('type')}: {err.get('message')}"
        detail = body.get("detail")
        if isinstance(detail, dict):
            return f"{detail.get('error_code')}: {detail.get('message')}"
        if detail is not None:
            return str(detail)[:300]
    return resp.text[:200]


def _classify(status: int, detail: str) -> ServiceError:
    if status in (401, 402, 403):
        return ServiceAuthError(SERVICE, detail, status)
    if status in (400, 422):
        return ServiceBadRequest(SERVICE, detail, status)
    if status == 429 or status >= 500:
        return ServiceUnavailable(SERVICE, detail, status)
    return ServiceError(SERVICE, detail, status)


async def synthesize(text: str) -> TTSResult:
    """Real Timbre call. Raises ServiceError subclasses on failure."""
    payload = {
        "text": spell_small_numbers(text),
        "voice": settings.TTS_VOICE,
        "model": settings.TTS_MODEL,
        "language": settings.TTS_LANGUAGE,
        "speed": settings.TTS_SPEED,
        "audio_config": settings.tts_audio_config(),
    }
    attempts = settings.RETRIES + 1
    async with httpx.AsyncClient(timeout=settings.TTS_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(settings.tts_url, headers=settings.gnani_headers(), json=payload)
            except httpx.TimeoutException:
                err: ServiceError = ServiceTimeout(SERVICE, f"timed out after {settings.TTS_TIMEOUT}s")
            except httpx.HTTPError as e:
                err = ServiceUnavailable(SERVICE, f"network error: {e!r}")
            else:
                ctype = resp.headers.get("content-type", "")
                if resp.status_code == 200:
                    if "json" in ctype or len(resp.content) < 100:
                        raise ServiceError(SERVICE, f"200 but no audio returned: {resp.text[:200]}", 200)
                    return TTSResult(audio=resp.content, content_type=ctype.split(";")[0] or "audio/wav")
                err = _classify(resp.status_code, _error_detail(resp))

            if not err.retryable or attempt == attempts:
                raise err
            log.warning("%s (attempt %d/%d), retrying", err, attempt, attempts)
            await asyncio.sleep(settings.RETRY_BACKOFF_SECONDS)
    raise ServiceError(SERVICE, "unreachable")


def mock_synthesize() -> TTSResult:
    """A short 440 Hz beep as a valid WAV, so the UI audio player always has something to play."""
    rate = settings.TTS_SAMPLE_RATE
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(rate * 0.6))
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return TTSResult(audio=buf.getvalue(), content_type="audio/wav", mocked=True)


async def synthesize_or_mock(text: str) -> TTSResult:
    """What the pipeline calls: mock if flagged, and automatic mock on any failure."""
    if settings.mock_tts:
        return mock_synthesize()
    try:
        return await synthesize(text)
    except ServiceError as e:
        log.warning("TTS failed, using mock: %s", e)
        return mock_synthesize()


async def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("text", nargs="?", default=SAMPLE)
    p.add_argument("--real", action="store_true", help="force the real API (ignore mock flags)")
    p.add_argument("--out", default="tests/samples/tts_out.wav")
    args = p.parse_args()

    if args.real or not settings.mock_tts:
        try:
            res = await synthesize(args.text)
        except ServiceError as e:
            print(f"FAILED: {e}")
            return 1
    else:
        print("(mock mode)")
        res = mock_synthesize()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(res.audio)
    print(f"saved {out} | {len(res.audio)} bytes | {res.content_type} | mocked={res.mocked}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(_main()))
