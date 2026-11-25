import hashlib
import json
from pathlib import Path

import whisper

from src.lock import AlreadyRunning, run_lock

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "incoming" / "audio"
OUT = ROOT / "incoming" / "calls"
OUTPUT = ROOT / "output"
LOCK_FILE = OUTPUT / "pipeline.lock"
HASH_FILE = OUTPUT / "audio_hashes.json"
AUDIO_TYPES = {".mp3", ".wav", ".m4a"}

# "small" balances speed and accuracy on a laptop. Try "medium" if results are poor.
MODEL_NAME = "medium"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hashes():
    if not HASH_FILE.exists():
        return {}
    text = HASH_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # A damaged hash file only causes extra transcription, so start fresh.
        return {}


def save_hashes(hashes):
    OUTPUT.mkdir(exist_ok=True)
    tmp = HASH_FILE.with_name("audio_hashes.tmp")
    tmp.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    tmp.replace(HASH_FILE)


def find_work(files, hashes):
    """Return (audio, digest, target) for each recording that is new, changed, or lost its transcript."""
    todo = []
    for audio in files:
        digest = file_hash(audio)
        target = OUT / f"{audio.stem}.txt"
        if hashes.get(audio.name) != digest or not target.exists():
            todo.append((audio, digest, target))
    return todo


def transcribe_all():
    OUT.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in AUDIO.iterdir() if p.suffix.lower() in AUDIO_TYPES)
    if not files:
        print("No audio files found in incoming\\audio")
        return

    hashes = load_hashes()
    todo = find_work(files, hashes)
    if not todo:
        print("No new or changed recordings.")
        return

    print(f"{len(todo)} recording(s) to transcribe.")
    model = whisper.load_model(MODEL_NAME)
    for audio, digest, target in todo:
        result = model.transcribe(str(audio))
        target.write_text(result["text"].strip(), encoding="utf-8")
        hashes[audio.name] = digest
        save_hashes(hashes)  # saved after each file, so a crash doesn't redo finished work
        print(f"transcribed {audio.name} -> {target.name} (language: {result.get('language')})")


def main():
    try:
        with run_lock(LOCK_FILE):
            transcribe_all()
    except AlreadyRunning as e:
        print(f"Skipped transcription: {e}")


if __name__ == "__main__":
    main()