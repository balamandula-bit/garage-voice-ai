import os
import httpx
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("SARVAM_API_KEY") or os.getenv("EVON_API_KEY")
print("Key loaded:", bool(key), "| starts with sk_:", (key or "").startswith("sk_"))

r = httpx.post(
    "https://api.sarvam.ai/v1/chat/completions",
    headers={"api-subscription-key": key, "Content-Type": "application/json"},
    json={
        "model": "sarvam-105b-conversations",
        "temperature": 0.1,
        "messages": [{"role": "user", "content": "Reply with only JSON: {\"ok\": true}"}],
    },
    timeout=30,
)
print("Status:", r.status_code)
print(r.text[:600])
