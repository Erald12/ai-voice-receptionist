import re
from pathlib import Path

# Matches Philippine mobile numbers: 09XX..., 9XX..., +63 9XX...
PHONE_PATTERN = re.compile(r"(?:\+?63[\s-]?|0)?9\d{2}[\s-]?\d{3}[\s-]?\d{4}")

REASONS = {"appointment_request", "billing_question", "service_question",
           "complaint", "emergency", "other"}
URGENCIES = {"emergency", "high", "normal", "low"}


def load_lines(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("//")]


def term_in(text, term):
    """Whole-word match for words; plain substring match for symbols like $ or ₱."""
    if term[0].isalnum():
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) is not None
    return term.lower() in text.lower()


def find_urgent(text, terms):
    return [t for t in terms if term_in(text, t)]


def normalize_phone(value):
    """Return an 11-digit 09XXXXXXXXX number, or None if the value isn't a valid mobile number."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("63") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits if len(digits) == 11 and digits.startswith("09") else None


def find_phone(text):
    """Fallback: find a phone number in the transcript if Claude didn't return one."""
    for match in PHONE_PATTERN.finditer(text):
        number = normalize_phone(match.group(0))
        if number:
            return number
    return None


def check_reply(reply, business_name, banned, allowed_numbers, caller_name=None):
    """Return a list of problems with a text-back draft. Empty means it passes."""
    if not reply.strip():
        return ["empty draft"]
    problems = []
    if len(reply) > 300:
        problems.append(f"draft is {len(reply)} chars (max 300)")
    if business_name.lower() not in reply.lower():
        problems.append("draft does not name the business")
    if caller_name:
        first = caller_name.split()[0]
        if first.lower() not in reply.lower():
            problems.append(f"draft does not use the caller's first name ({first})")
    for term in banned:
        if term_in(reply, term):
            problems.append(f"banned phrase: {term}")
    for number in re.findall(r"\d+", reply):
        if number not in allowed_numbers:
            problems.append(f"number not in business info or caller text: {number}")
    return problems

def find_partial_number(text):
    """Return a digit-like sequence that failed validation, so staff can check it."""
    match = re.search(r"\d[\d\s-]{6,}\d", text)
    return match.group(0).strip() if match else None