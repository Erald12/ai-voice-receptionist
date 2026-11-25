import csv
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

from src.extract import BUSINESS, extract_call
from src.lock import AlreadyRunning, run_lock
from src.rules import check_reply, find_partial_number, find_phone, find_urgent, load_lines, normalize_phone

ROOT = Path(__file__).resolve().parent.parent
CALLS_DIR = ROOT / "incoming" / "calls"
AUDIO_DIR = ROOT / "incoming" / "audio"
CONFIG_DIR = ROOT / "config"
OUTPUT = ROOT / "output"
STATE_FILE = OUTPUT / "state.json"
QUEUE_FILE = OUTPUT / "callback_queue.md"
RUN_LOG = OUTPUT / "run_log.csv"
LOCK_FILE = OUTPUT / "pipeline.lock"
LOG_COLS = ["timestamp", "files_seen", "escalate", "callback", "missing_number",
            "invalid", "failed", "skipped", "seconds", "status"]
BUSINESS_TEXT = json.dumps(BUSINESS, ensure_ascii=False)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state():
    if not STATE_FILE.exists():
        return {}
    text = STATE_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        backup = STATE_FILE.with_name("state.corrupt.json")
        STATE_FILE.replace(backup)
        print(f"state.json was unreadable; moved to {backup.name} and starting fresh.")
        return {}


def save_state(state):
    OUTPUT.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_name("state.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def decide_lane(urgent_found, verdict, phone):
    """Escalation wins over everything. Then missing numbers. Otherwise a normal callback."""
    if urgent_found or verdict["urgency"] == "emergency":
        return "escalate"
    if not phone:
        return "missing_number"
    return "callback"


def from_voice(path):
    """A transcript with a matching audio file came from a recording."""
    return any(AUDIO_DIR.glob(f"{path.stem}.*"))


def process_call(path, banned, urgent_terms):
    transcript = path.read_text(encoding="utf-8").strip()
    if not transcript:
        return "invalid", {"problem": "empty transcript"}

    urgent_found = find_urgent(transcript, urgent_terms)
    verdict = extract_call(transcript)
    if verdict is None:
        return "failed", {"problem": "Claude reply could not be parsed after retry"}

    claude_phone = normalize_phone(verdict.get("callback_number"))
    fallback_phone = None if claude_phone else find_phone(transcript)
    phone = claude_phone or fallback_phone
    phone_source = "claude" if claude_phone else ("transcript" if fallback_phone else "none")
    lane = decide_lane(urgent_found, verdict, phone)

    draft, draft_problems = "", []
    if lane == "callback":
        draft = verdict["sms_draft"]
        allowed = set(re.findall(r"\d+", BUSINESS_TEXT + transcript))
        draft_problems = check_reply(draft, BUSINESS["business_name"], banned, allowed,
                                     verdict.get("caller_name"))

    voice = from_voice(path)
    record = {
        "caller_name": verdict.get("caller_name"),
        "phone": phone,
        "phone_source": phone_source,
        "verify_phone": voice or phone_source == "transcript",
        "from_voice": voice,
        "reason": verdict["reason"],
        "urgency": verdict["urgency"],
        "summary": verdict["summary"],
        "draft": draft,
        "draft_problems": draft_problems,
        "urgent_terms": urgent_found,
    }

    return lane, record


def item_lines(name, rec, by_phone):
    phone = rec.get("phone")
    lines = [f"### {name}", ""]
    lines.append(f"- **Caller:** {rec.get('caller_name') or 'not stated'}")

    if rec.get("partial_number") and not phone:
        lines.append(f"- **Possible number heard (incomplete, verify):** {rec['partial_number']}")

    number = phone or "not stated"
    if phone and rec.get("verify_phone"):
        number += " (verify before calling: came from a voice recording)"
    lines.append(f"- **Number:** {number}")

    others = [n for n in by_phone.get(phone, []) if n != name] if phone else []
    if others:
        lines.append(f"- **Same number also on:** {', '.join(others)}")

    lines.append(f"- **Reason:** {rec.get('reason')}")
    lines.append(f"- **Urgency:** {rec.get('urgency')}")
    lines.append(f"- **Summary:** {rec.get('summary')}")
    if rec.get("urgent_terms"):
        lines.append(f"- **Urgent keywords found:** {', '.join(rec['urgent_terms'])}")
    if rec.get("draft"):
        lines += ["- **Text-back draft (NOT SENT):**", "", f"  > {rec['draft']}", ""]
    if rec.get("draft_problems"):
        lines.append(f"- **Draft problems (edit before sending):** {'; '.join(rec['draft_problems'])}")
    lines.append("")
    return lines


def write_queue(state):
    OUTPUT.mkdir(exist_ok=True)
    by_phone = {}
    for name, rec in state.items():
        if rec.get("phone"):
            by_phone.setdefault(rec["phone"], []).append(name)
    for names in by_phone.values():
        names.sort()

    groups = {"escalate": [], "callback": [], "missing_number": []}
    for name, rec in sorted(state.items()):
        groups.get(rec.get("lane"), []).append((name, rec))

    lines = ["# Missed call queue", "",
             f"Updated {datetime.now().isoformat(timespec='seconds')}", ""]

    lines += ["## 1. Escalate now", "",
              "Urgent or emergency calls. Call back immediately, do not wait for the queue. "
              "If someone is in immediate danger, call 911.", ""]
    if not groups["escalate"]:
        lines += ["None.", ""]
    for name, rec in groups["escalate"]:
        lines += item_lines(name, rec, by_phone)

    lines += ["## 2. Callbacks to make", "",
              "Confirm the number, then call. Send a text-back only after staff approve the draft. "
              "Nothing is sent automatically.", ""]
    if not groups["callback"]:
        lines += ["None.", ""]
    for name, rec in groups["callback"]:
        lines += item_lines(name, rec, by_phone)

    lines += ["## 3. Missing callback number", "",
              "Find the number in your phone log or CRM before calling back.", ""]
    if not groups["missing_number"]:
        lines += ["None.", ""]
    for name, rec in groups["missing_number"]:
        lines += item_lines(name, rec, by_phone)

    QUEUE_FILE.write_text("\n".join(lines), encoding="utf-8")


def append_run_log(entry):
    new_file = not RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLS)
        if new_file:
            writer.writeheader()
        writer.writerow(entry)


def run():
    OUTPUT.mkdir(exist_ok=True)
    start = time.time()
    state = load_state()
    banned = load_lines(CONFIG_DIR / "banned_phrases.txt")
    urgent_terms = load_lines(CONFIG_DIR / "urgent_terms.txt")
    files = sorted(CALLS_DIR.glob("*.txt"))

    # Drop state for transcripts that no longer exist
    present = {p.name for p in files}
    state = {name: rec for name, rec in state.items() if name in present}

    counts = {"escalate": 0, "callback": 0, "missing_number": 0,
              "invalid": 0, "failed": 0, "skipped": 0}
    status = "crashed"

    try:
        for path in files:
            digest = file_hash(path)
            if state.get(path.name, {}).get("hash") == digest:
                counts["skipped"] += 1
                continue

            try:
                lane, record = process_call(path, banned, urgent_terms)
            except Exception as e:  # one bad transcript shouldn't stop the batch
                lane, record = "failed", {"problem": f"{type(e).__name__}: {e}"}

            counts[lane] += 1
            print(f"{path.name}: {lane}")
            if lane in {"failed", "invalid"}:
                state.pop(path.name, None)  # not remembered, so the next run retries it
                continue

            record.update({
                "lane": lane,
                "hash": digest,
                "date": datetime.now().isoformat(timespec="seconds"),
            })
            state[path.name] = record

        write_queue(state)
        failures = counts["failed"] + counts["invalid"]
        status = "ok" if failures == 0 else "partial"
    finally:
        save_state(state)
        append_run_log({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "files_seen": len(files),
            "escalate": counts["escalate"],
            "callback": counts["callback"],
            "missing_number": counts["missing_number"],
            "invalid": counts["invalid"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "seconds": round(time.time() - start, 1),
            "status": status,
        })

    print(f"Done. {counts['escalate']} escalate, {counts['callback']} callback, "
          f"{counts['missing_number']} missing number, {counts['skipped']} unchanged. "
          f"Queue: output\\callback_queue.md")


def main():
    try:
        with run_lock(LOCK_FILE):
            run()
    except AlreadyRunning as e:
        print(f"Skipped: {e}")


if __name__ == "__main__":
    main()