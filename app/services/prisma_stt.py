"""Prisma STT wrapper (Gnani). Real call with timeout + one retry, plus mock fallback.

Standalone test:  python -m app.services.prisma_stt <audio file> [--real] [--format transcribe]
"""
import argparse
import asyncio
import logging
import mimetypes
import sys
import time
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
SERVICE = "prisma_stt"

MOCK_TRANSCRIPT = (
    "KA 01 AB 1234 Swift gaadi hai. Engine theek hai, clutch thoda hard hai, "
    "brake pad ghis gaye hain, battery OK hai."
)


@dataclass
class STTResult:
    transcript: str
    model: str = ""
    language: Optional[str] = None
    latency: float = 0.0
    mocked: bool = False


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or "no response body"
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):  # {"success": false, "error": {"type", "message"}}
            return f"{err.get('type')}: {err.get('message')}"
        detail = body.get("detail")
        if isinstance(detail, dict):  # gateway: auth / rate limit
            return f"{detail.get('error_code')}: {detail.get('message')}"
        if detail is not None:  # 422 validation list
            return str(detail)[:300]
        if body.get("code"):  # 504 UPSTREAM_TIMEOUT shape
            return f"{body.get('code')}: {body.get('message')}"
    return resp.text[:200]


def _classify(status: int, detail: str) -> ServiceError:
    if status in (401, 402, 403):
        return ServiceAuthError(SERVICE, detail, status)
    if status in (400, 422):
        return ServiceBadRequest(SERVICE, detail, status)
    if status == 429 or status >= 500:
        return ServiceUnavailable(SERVICE, detail, status)
    return ServiceError(SERVICE, detail, status)


def _parse(resp: httpx.Response, elapsed: float) -> STTResult:
    try:
        body = resp.json()
    except ValueError:
        raise ServiceError(SERVICE, "response was not valid JSON", resp.status_code)
    transcript = body.get(settings.STT_FIELD_TRANSCRIPT) if isinstance(body, dict) else None
    if not isinstance(transcript, str):
        raise ServiceError(
            SERVICE, f"no '{settings.STT_FIELD_TRANSCRIPT}' string in response: {str(body)[:200]}"
        )
    # An empty transcript means "no speech heard". Not an error; the pipeline decides.
    return STTResult(
        transcript=transcript.strip(),
        model=body.get("model", ""),
        language=body.get("detected_language_code"),
        latency=body.get("end_to_end_latency") or elapsed,
    )


async def transcribe(
    audio: bytes,
    filename: str = "audio.wav",
    content_type: Optional[str] = None,
    *,
    fmt: Optional[str] = None,
) -> STTResult:
    """Real Prisma call. Raises ServiceError subclasses on failure."""
    content_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    data = {"language_code": settings.STT_LANGUAGE_CODE}
    if settings.STT_MODEL:
        data["model"] = settings.STT_MODEL
    fmt = fmt if fmt is not None else settings.STT_FORMAT
    if fmt:
        data["format"] = fmt
    if settings.STT_KEYTERMS:
        data["keyterms"] = settings.STT_KEYTERMS
    if settings.STT_TOPIC:
        data["topic"] = settings.STT_TOPIC

    attempts = settings.RETRIES + 1
    async with httpx.AsyncClient(timeout=settings.STT_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            try:
                resp = await client.post(
                    settings.stt_url,
                    headers=settings.gnani_headers(),
                    files={settings.STT_FIELD_AUDIO: (filename, audio, content_type)},
                    data=data,
                )
            except httpx.TimeoutException:
                err: ServiceError = ServiceTimeout(SERVICE, f"timed out after {settings.STT_TIMEOUT}s")
            except httpx.HTTPError as e:
                err = ServiceUnavailable(SERVICE, f"network error: {e!r}")
            else:
                if resp.status_code == 200:
                    return _parse(resp, time.perf_counter() - start)
                err = _classify(resp.status_code, _error_detail(resp))

            if not err.retryable or attempt == attempts:
                raise err
            log.warning("%s (attempt %d/%d), retrying", err, attempt, attempts)
            await asyncio.sleep(settings.RETRY_BACKOFF_SECONDS)
    raise ServiceError(SERVICE, "unreachable")  # keeps type checkers happy


def mock_transcribe() -> STTResult:
    return STTResult(transcript=MOCK_TRANSCRIPT, model="mock", language="hi-IN", mocked=True)


async def transcribe_or_mock(
    audio: bytes, filename: str = "audio.wav", content_type: Optional[str] = None
) -> STTResult:
    """What the pipeline calls: mock if flagged, and automatic mock on any failure."""
    if settings.mock_stt:
        return mock_transcribe()
    try:
        return await transcribe(audio, filename, content_type)
    except ServiceError as e:
        log.warning("STT failed, using mock: %s", e)
        return mock_transcribe()


async def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--format", default=None, help="verbatim | transcribe | codemix | transliterate")
    p.add_argument("--real", action="store_true", help="force the real API (ignore mock flags)")
    args = p.parse_args()

    if args.real or not settings.mock_stt:
        audio = Path(args.audio).read_bytes()
        try:
            res = await transcribe(audio, Path(args.audio).name, fmt=args.format)
        except ServiceError as e:
            print(f"FAILED: {e}")
            return 1
    else:
        print("(mock mode)")
        res = mock_transcribe()

    print(f"transcript: {res.transcript}")
    print(f"model={res.model} language={res.language} latency={res.latency:.2f}s mocked={res.mocked}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(_main()))
