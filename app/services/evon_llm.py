"""Evon LLM wrapper (OpenAI-compatible /v1/chat/completions) + rule-based mock.

Standalone test:  python -m app.services.evon_llm ["transcript text"] [--real]
"""
import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings
from app.prompts import build_messages
from app.schemas import ComponentStatus, InspectionCard, Status
from app.services import (
    ServiceAuthError,
    ServiceBadRequest,
    ServiceError,
    ServiceTimeout,
    ServiceUnavailable,
)

log = logging.getLogger(__name__)
SERVICE = "evon_llm"

SAMPLE = "KA 01 AB 1234, Swift engine ठीक है। clutch तो रखा है, brake pad घिस गए हैं।"


@dataclass
class LLMResult:
    card: InspectionCard
    mocked: bool = False


# ---------------------------------------------------------------- real call
def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if isinstance(body, dict) and body.get("detail"):
            return str(body["detail"])[:300]
    except ValueError:
        pass
    return resp.text[:200] or "no response body"


def _classify(status: int, detail: str) -> ServiceError:
    if status in (401, 402, 403):
        return ServiceAuthError(SERVICE, detail, status)
    if status in (400, 422):
        return ServiceBadRequest(SERVICE, detail, status)
    if status == 429 or status >= 500:
        return ServiceUnavailable(SERVICE, detail, status)
    return ServiceError(SERVICE, detail, status)


async def _chat(messages: list[dict]) -> str:
    if not settings.EVON_BASE_URL:
        raise ServiceError(SERVICE, "EVON_BASE_URL is not set")
    body = {
        "model": settings.EVON_MODEL,
        "messages": messages,
        "temperature": settings.EVON_TEMPERATURE,
        "max_tokens": settings.EVON_MAX_TOKENS,
    }
    attempts = settings.RETRIES + 1
    async with httpx.AsyncClient(timeout=settings.EVON_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(settings.evon_url, headers=settings.evon_headers(), json=body)
            except httpx.TimeoutException:
                err: ServiceError = ServiceTimeout(SERVICE, f"timed out after {settings.EVON_TIMEOUT}s")
            except httpx.HTTPError as e:
                err = ServiceUnavailable(SERVICE, f"network error: {e!r}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()["choices"][0]["message"]["content"] or ""
                    except (ValueError, KeyError, IndexError, TypeError):
                        raise ServiceError(SERVICE, f"unexpected response shape: {resp.text[:200]}", 200)
                err = _classify(resp.status_code, _error_detail(resp))

            if not err.retryable or attempt == attempts:
                raise err
            log.warning("%s (attempt %d/%d), retrying", err, attempt, attempts)
            await asyncio.sleep(settings.RETRY_BACKOFF_SECONDS)
    raise ServiceError(SERVICE, "unreachable")


def _extract_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(t[start : end + 1])


def _validate(raw: str) -> InspectionCard:
    return InspectionCard.model_validate(_extract_json(raw))


async def extract_card(transcript: str) -> InspectionCard:
    """Evon -> validated card. One validation retry, then safe default.
    Raises ServiceError only if the API itself fails."""
    raw = await _chat(build_messages(transcript))
    try:
        return _validate(raw)
    except ValueError as e:  # covers JSONDecodeError and pydantic ValidationError
        log.warning("Evon output failed validation, retrying once: %s", str(e)[:200])
        raw2 = await _chat(build_messages(transcript, error=str(e), bad_output=raw))
        try:
            return _validate(raw2)
        except ValueError as e2:
            log.error("Evon output failed validation twice, using safe default: %s", str(e2)[:200])
            return InspectionCard.safe_default()


# ---------------------------------------------------------------- mock (rule-based)
_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पांच": "5", "पाँच": "5", "छह": "6", "सात": "7", "आठ": "8", "नौ": "9",
}
_MODELS = [
    "swift", "alto", "i20", "i10", "creta", "baleno", "dzire", "splendor", "activa",
    "bolero", "scorpio", "innova", "nexon", "punch", "verna", "ertiga", "brezza", "ciaz",
]
_COMPONENTS = {
    "engine_condition": ["engine", "इंजन", "motor"],
    "clutch_transmission": ["clutch", "gear", "transmission", "क्लच", "गियर"],
    "brakes_suspension": ["brake", "suspension", "shock", "ब्रेक"],
    "body_paint_condition": ["body", "paint", "dent", "scratch", "bumper", "बॉडी"],
    "battery_electricals": ["battery", "light", "horn", "wiring", "electrical", "बैटरी"],
}
_SHORT = {
    "engine_condition": "engine", "clutch_transmission": "clutch", "brakes_suspension": "brake",
    "body_paint_condition": "body", "battery_electricals": "battery",
}
_BAD = ["kharab", "खराब", "dead", "band", "बंद", "toot", "टूट", "fail", "leak", "jam", "bekar", "बेकार", "replace"]
_WARN = ["thoda", "थोड", "hard", "awaaz", "आवाज", "noise", "ghis", "घिस", "weak", "slow", "dent", "fade", "loose", "vibrat", "scratch"]
_OK = ["theek", "thik", "tk", "tik", "thek", "ठीक", "sahi", "सही", "ok", "fine", "good", "badhiya", "बढ़िया"]
_NEG = ["nahi", "nahin", "नहीं", "नही"]
_RANK = {Status.NOT_CHECKED: 0, Status.OK: 1, Status.WARNING: 2, Status.DEFECTIVE: 3}


def _has(tokens: list[str], words: list[str]) -> bool:
    return any(t.startswith(w) for t in tokens for w in words)


def _tokens(clause: str) -> list[str]:
    return [t.strip("\"'()[].,;:!?।") for t in clause.lower().split()]


def _clause_status(tokens: list[str]) -> Status:
    if _has(tokens, _BAD):
        return Status.DEFECTIVE
    if _has(tokens, _WARN):
        return Status.WARNING
    if _has(tokens, _OK):
        return Status.WARNING if _has(tokens, _NEG) else Status.OK
    return Status.NOT_CHECKED


def _find_vehicle_number(text: str) -> str:
    text = re.sub(r"[,.।;]", " ", text)
    mapped = " ".join(_DIGITS.get(t.lower(), t) for t in text.split())
    mapped = re.sub(r"(?<=\d) (?=\d)", "", mapped).upper()
    m = re.search(r"\b([A-Z]\s?[A-Z])[\s-]*(\d{1,2})[\s-]*([A-Z](?:\s?[A-Z]){0,2})[\s-]*(\d{4})\b", mapped)
    if not m:
        return "UNKNOWN"
    return "-".join([m.group(1).replace(" ", ""), m.group(2).zfill(2), m.group(3).replace(" ", ""), m.group(4)])


def mock_extract(transcript: str) -> InspectionCard:
    """Keyword-based Hinglish extractor. Used when Evon is unavailable."""
    results = {k: (Status.NOT_CHECKED, None) for k in _COMPONENTS}
    rest_ok = False
    for clause in re.split(r"[.,;।!?\n]+", transcript):
        tokens = _tokens(clause)
        if not tokens:
            continue
        status = _clause_status(tokens)
        if "baaki" in tokens and status == Status.OK:
            rest_ok = True
        for comp, keywords in _COMPONENTS.items():
            if _has(tokens, keywords) and _RANK[status] > _RANK[results[comp][0]]:
                notes = clause.strip()[:60] if status in (Status.WARNING, Status.DEFECTIVE) else None
                results[comp] = (status, notes)
    if rest_ok:
        results = {k: ((Status.OK, None) if v[0] == Status.NOT_CHECKED else v) for k, v in results.items()}

    statuses = [s for s, _ in results.values()]
    if all(s == Status.NOT_CHECKED for s in statuses):
        score = 0
    else:
        score = max(0, 10 - statuses.count(Status.WARNING) - 3 * statuses.count(Status.DEFECTIVE))

    model = next((m.title() for m in _MODELS if m in _tokens(transcript)), "UNKNOWN")
    ok = [_SHORT[k] for k, (s, _) in results.items() if s == Status.OK]
    bad = [_SHORT[k] for k, (s, _) in results.items() if s in (Status.WARNING, Status.DEFECTIVE)]
    parts = []
    if ok:
        parts.append(" aur ".join(ok) + " theek hai")
    if bad:
        parts.append(" aur ".join(bad) + " mein dikkat hai")
    if parts:
        head = f"{model} check ho gayi" if model != "UNKNOWN" else "Gaadi check ho gayi"
        summary = f"{head}: {', '.join(parts)}. Score {score} out of 10."
    else:
        summary = "Kuch samajh nahi aaya, dobara bolo."

    return InspectionCard(
        vehicle_number=_find_vehicle_number(transcript),
        vehicle_model=model,
        **{k: ComponentStatus(status=s, notes=n) for k, (s, n) in results.items()},
        overall_score=score,
        mechanic_summary_hindi=summary,
    )


async def extract_card_or_mock(transcript: str) -> LLMResult:
    """What the pipeline calls: mock if flagged, and automatic mock on any API failure."""
    if settings.mock_llm:
        return LLMResult(mock_extract(transcript), mocked=True)
    try:
        return LLMResult(await extract_card(transcript))
    except ServiceError as e:
        log.warning("LLM failed, using mock: %s", e)
        return LLMResult(mock_extract(transcript), mocked=True)


async def _main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("transcript", nargs="?", default=SAMPLE)
    p.add_argument("--real", action="store_true", help="force the real Evon call (ignore mock flags)")
    args = p.parse_args()

    if args.real:
        try:
            res = LLMResult(await extract_card(args.transcript))
        except ServiceError as e:
            print(f"FAILED: {e}")
            return 1
    else:
        res = await extract_card_or_mock(args.transcript)

    print(res.card.model_dump_json(indent=1))
    print(f"mocked={res.mocked}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(_main()))
