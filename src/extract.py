import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.rules import REASONS, URGENCIES

load_dotenv()
MODEL = "claude-haiku-5-5"
ROOT = Path(__file__).resolve().parent.parent

BUSINESS_FILE = ROOT / "config" / "business.json"
if not BUSINESS_FILE.exists():
    sys.exit("config/business.json is missing.")
BUSINESS = json.loads(BUSINESS_FILE.read_text(encoding="utf-8"))

client = anthropic.Anthropic(max_retries=3)

SYSTEM = """You process missed-call voicemail transcripts for BUSINESS_NAME_TOKEN.

Business information (the only facts you may use):
BUSINESS_JSON_TOKEN

Rules:
- Use only what the caller actually said. Use null for any field the caller did not state.
- Never diagnose, give medical, legal, or financial advice, or describe treatments.
- Never confirm appointment times, prices, or availability.
- If the caller describes an emergency (someone injured, not breathing, a fire, a crime in progress, threats of harm), set urgency to "emergency".
- The sms_draft must be under 300 characters. It must start with "Hi" and the caller's first name if known, say it is an automated message from BUSINESS_NAME_TOKEN, say that our staff will call back during office hours, and contain no times, prices, or medical information.

Reply only with JSON, no other text:
{"caller_name": string or null,
 "callback_number": string or null,
 "reason": one of "appointment_request", "billing_question", "service_question", "complaint", "emergency", "other",
 "urgency": one of "emergency", "high", "normal", "low",
 "summary": "one sentence describing the call",
 "sms_draft": "the text message to send after staff approval"}
"""


def parse_verdict(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    for key in ("caller_name", "callback_number"):
        if data.get(key) is not None and not isinstance(data.get(key), str):
            return None
    if data.get("reason") not in REASONS or data.get("urgency") not in URGENCIES:
        return None
    for key in ("summary", "sms_draft"):
        if not isinstance(data.get(key), str):
            return None
    return data


def extract_call(transcript):
    system = (SYSTEM
              .replace("BUSINESS_NAME_TOKEN", BUSINESS["business_name"])
              .replace("BUSINESS_JSON_TOKEN", json.dumps(BUSINESS, indent=2, ensure_ascii=False)))
    for _ in range(2):  # one retry if the reply can't be parsed
        message = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "Voicemail transcript:\n" + transcript}],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        verdict = parse_verdict(text)
        if verdict:
            return verdict
    return None