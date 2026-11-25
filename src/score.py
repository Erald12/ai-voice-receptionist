import json
import sys
from pathlib import Path

from src.rules import normalize_phone

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "output" / "state.json"
EXPECTED_FILE = ROOT / "ground_truth" / "expected.json"


def load_json(path, hint):
    if not path.exists():
        sys.exit(f"Missing: {path.relative_to(ROOT)}. {hint}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(f"{path.relative_to(ROOT)} is empty. {hint}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"{path.relative_to(ROOT)} is not valid JSON: {e}")


def main():
    state = load_json(STATE_FILE, "Run python -m src.main first.")
    expected = load_json(EXPECTED_FILE, "Create it with the content from the setup steps.")

    phone_hits = lane_hits = urgent_hits = urgent_total = 0
    for name, exp in expected.items():
        rec = state.get(name)
        if rec is None:
            print(f"{name}: no result. Check that the transcript exists in incoming\\calls\\.")
            continue

        exp_phone = normalize_phone(exp.get("phone"))
        got_phone = rec.get("phone")
        phone_ok = exp_phone == got_phone
        lane_ok = exp.get("lane") == rec.get("lane")
        phone_hits += phone_ok
        lane_hits += lane_ok

        for term in exp.get("urgent_terms", []):
            urgent_total += 1
            if term in rec.get("urgent_terms", []):
                urgent_hits += 1

        phone_text = "OK" if phone_ok else f"MISS (expected {exp_phone}, got {got_phone})"
        lane_text = "OK" if lane_ok else f"MISS (expected {exp.get('lane')}, got {rec.get('lane')})"
        print(f"{name}\n  phone: {phone_text}\n  lane:  {lane_text}")

    total = len(expected)
    print()
    print(f"Phone accuracy: {phone_hits}/{total}")
    print(f"Lane accuracy:  {lane_hits}/{total}")
    if urgent_total:
        print(f"Urgent term recall: {urgent_hits}/{urgent_total}")


if __name__ == "__main__":
    main()