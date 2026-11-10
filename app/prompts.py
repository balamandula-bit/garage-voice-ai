"""Evon system prompt + Hinglish few-shot examples."""
import json
from typing import Optional

SYSTEM_PROMPT = """You are the inspection-card extractor for an Indian garage voice app.
Input: a speech-to-text transcript of a mechanic speaking Hinglish (Hindi + English, Roman or Devanagari script). It may contain recognition errors and noise artifacts.
Output: ONE JSON object and nothing else. No markdown, no explanation.

Schema (exact keys):
{
  "vehicle_number": string,
  "vehicle_model": string,
  "engine_condition": {"status": "OK|WARNING|DEFECTIVE|NOT_CHECKED", "notes": string or null},
  "clutch_transmission": {same shape},
  "brakes_suspension": {same shape},
  "body_paint_condition": {same shape},
  "battery_electricals": {same shape},
  "overall_score": integer 0-10,
  "mechanic_summary_hindi": string
}

Rules:
1. Status must be exactly OK, WARNING, DEFECTIVE or NOT_CHECKED.
   OK = working fine. WARNING = worn, weak, noisy, needs attention soon. DEFECTIVE = failed, broken, needs repair or replacement now.
2. Only mark what the mechanic actually said. Anything not mentioned is NOT_CHECKED with notes null. Exception: if he says everything else is fine ("baaki sab theek"), mark the remaining components OK.
3. notes: at most 10 words, plain English or Hinglish, what he said about the part. null if OK.
4. vehicle_number: uppercase with hyphens, like KA-01-AB-1234. Convert spoken digits and letters ("zero one" -> 01). If not clearly stated use "UNKNOWN". Never invent. vehicle_model: same rule, "UNKNOWN" if not said.
5. overall_score = 10 minus 1 per WARNING minus 3 per DEFECTIVE, minimum 0. If nothing was checked, 0.
6. mechanic_summary_hindi: ONE short Hinglish sentence in Roman script, at most 25 words, spoken back to the mechanic: what is OK, what needs attention, and the score. Do not read out the vehicle number; mention the model name if known.
7. If a word looks like a misheard part name, use the context. If unsure, leave that component NOT_CHECKED."""


def _c(status: str = "NOT_CHECKED", notes: Optional[str] = None) -> dict:
    return {"status": status, "notes": notes}


def _card(vn, vm, eng, clu, brk, body, bat, score, summary) -> dict:
    return {
        "vehicle_number": vn,
        "vehicle_model": vm,
        "engine_condition": eng,
        "clutch_transmission": clu,
        "brakes_suspension": brk,
        "body_paint_condition": body,
        "battery_electricals": bat,
        "overall_score": score,
        "mechanic_summary_hindi": summary,
    }


FEW_SHOTS = [
    (
        "KA 01 AB 1234 Swift. Engine theek hai, clutch thoda hard hai, brake pad ghis gaye hain, battery OK hai.",
        _card(
            "KA-01-AB-1234", "Swift",
            _c("OK"), _c("WARNING", "clutch thoda hard"), _c("DEFECTIVE", "brake pads ghis gaye, replace karna hai"),
            _c(), _c("OK"), 6,
            "Swift check ho gayi: engine aur battery theek hain, clutch thoda hard hai aur brake pad badalne padenge. Score 6 out of 10.",
        ),
    ),
    (
        "T S zero nine E R four five six seven Alto. Body pe dent hai aur paint fade ho gaya. Battery weak hai. Baaki sab theek hai.",
        _card(
            "TS-09-ER-4567", "Alto",
            _c("OK"), _c("OK"), _c("OK"), _c("WARNING", "dent aur paint fade"), _c("WARNING", "battery weak"), 8,
            "Alto check ho gayi: engine, clutch aur brake theek hain, body aur battery par dhyan do. Score 8 out of 10.",
        ),
    ),
    (
        "uh gaadi ka clutch plate kharab hai... [noise] gaadi band ho jaati hai",
        _card(
            "UNKNOWN", "UNKNOWN",
            _c(), _c("DEFECTIVE", "clutch plate kharab"), _c(), _c(), _c(), 7,
            "Clutch plate kharab hai, turant repair karna padega. Score 7 out of 10.",
        ),
    ),
]


def build_messages(
    transcript: str, error: Optional[str] = None, bad_output: Optional[str] = None
) -> list[dict]:
    """Chat messages for Evon. Pass error + bad_output to build the validation-retry request."""
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for text, card in FEW_SHOTS:
        messages.append({"role": "user", "content": f"Transcript: {text}"})
        messages.append({"role": "assistant", "content": json.dumps(card, ensure_ascii=False)})
    messages.append({"role": "user", "content": f"Transcript: {transcript}"})
    if error:
        messages.append({"role": "assistant", "content": bad_output or ""})
        messages.append(
            {
                "role": "user",
                "content": f"That output failed validation:\n{error[:800]}\nReturn the corrected JSON object only.",
            }
        )
    return messages
