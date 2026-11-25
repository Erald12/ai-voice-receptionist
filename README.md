# AI Voice Receptionist (Missed-Call Triage)

A Python workflow that turns missed-call voicemails into a prioritized callback queue for staff. It transcribes voicemail recordings with Whisper, extracts the caller's details with Claude, applies safety rules in Python, and writes a queue file. **It does not answer live calls, and it never sends messages automatically.** Every text-back is a draft that a person must approve.

## Workflow

```
 Missed call
     │
     ▼
 Voicemail recording saved ──────────────► incoming/audio/
     │                                      (.mp3, .wav, .m4a)
     ▼
 [1] TRANSCRIBE  (Python + Whisper)
     Converts new or changed recordings to text.
     Unchanged recordings are skipped.
     │
     ▼                                      incoming/calls/*.txt
 [2] EXTRACT  (Claude)
     Pulls out caller name, callback number, reason,
     urgency, summary, and a draft text-back.
     Output must match a fixed JSON format, or it is retried once.
     │
     ▼
 [3] CHECK  (Python rules)
     • Urgent keywords ("swallowed", "not breathing", ...)
     • Phone number validated as an 11-digit 09XX number
     • Draft checked for banned phrases, length, business name,
       caller's first name, and numbers not in the source
     │
     ▼
 [4] ROUTE  (Python)
     ┌─────────────────────┬──────────────────────┬───────────────────────┐
     │ 1. ESCALATE NOW     │ 2. CALLBACK          │ 3. MISSING NUMBER     │
     │ Urgent keyword or   │ Valid number found   │ No valid number       │
     │ emergency urgency   │                      │ (partial numbers are  │
     │                     │                      │ shown for checking)   │
     └─────────────────────┴──────────────────────┴───────────────────────┘
     │
     ▼
 [5] QUEUE  (Python)
     Writes output/callback_queue.md, sorted by lane, plus
     output/run_log.csv and output/state.json.
     │
     ▼
 [6] STAFF ACTION  (human)
     • Escalate: call immediately. If someone is in danger, call 911.
     • Callback: confirm the number, call, and send a text only
       after approving the draft.
     • Missing number: find it in the phone log or CRM first.
     • Record the outcome: called, texted, not needed, or no answer.
```

**Where a person decides**

- **Escalations** are acted on by staff, not the queue. The queue only lists them.
- **Every text-back** is sent by a person after reading the draft against the caller's number and name.
- **Numbers from recordings** are marked "verify before calling."
- **Unclear or failed items** go to review rather than being guessed.

**What the workflow relies on**

- A recording exists and is audible. A missing or unclear voicemail goes nowhere.
- Transcription is accurate enough to catch urgent words and digits. Errors here carry through every later step.
- The queue is read promptly. Escalations are only as fast as the person who reads them.

## What it does not do

- It does not answer or place calls.
- It does not send texts or emails.
- It does not replace a person watching for emergencies. Emergency detection depends on the keyword list and on transcription quality, and both can miss things.
- It does not give medical, legal, or pricing information.

## Project structure

```
ai-voice-receptionist/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── run_receptionist.bat
├── config/
│   ├── business.json          # business facts Claude may use (sample values)
│   ├── urgent_terms.txt       # keywords that always escalate
│   └── banned_phrases.txt     # words a text-back must never contain
├── incoming/                  # not committed
│   ├── audio/                 # voicemail recordings (.mp3, .wav, .m4a)
│   └── calls/                 # transcripts, one .txt per recording
├── ground_truth/              # not committed: hand-labeled answer key
├── output/                    # not committed: queue, state, logs
└── src/
    ├── lock.py                # prevents overlapping runs
    ├── rules.py               # phone, keyword, and draft checks
    ├── extract.py             # Claude extraction with validated JSON
    ├── transcribe.py          # Whisper transcription, re-runs only changed audio
    ├── main.py                # routing, queue file, run log
    └── score.py               # compares results to the answer key (testing only)
```

## Requirements

- Python 3.10 or later
- ffmpeg on your PATH (needed by Whisper)
- An Anthropic API key

## Setup

```powershell
cd D:\PythonProject\ai-voice-receptionist
python -m venv ..\.venv          # skip if the shared venv exists
..\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` and replace `your_key_here` with your key. Do not commit this file.

Replace the sample values in `config/business.json` with the business's real details, and keep them free of anything you wouldn't publish.

## Running it

```powershell
python -m src.transcribe   # transcribes new or changed recordings
python -m src.main         # builds the queue
```

Open `output\callback_queue.md`. The queue is sorted into three sections, and each item shows the summary, the number (with a warning if it came from a recording), and any draft with its problems listed.

The batch file `run_receptionist.bat` runs both steps. Schedule it with:

```powershell
schtasks /create /tn "VoiceReceptionist" /tr "D:\PythonProject\ai-voice-receptionist\run_receptionist.bat" /sc minute /mo 15
```

## Testing accuracy

`src.score` compares the pipeline's results with `ground_truth/expected.json`, which is written by hand from the scripts and the audio before running the pipeline.

```powershell
python -m src.score
```

It reports phone accuracy, lane accuracy, and recall for urgent keywords. An incomplete number that was flagged for staff counts as a miss for the phone check, which is intentional.

## Known limits

- **Transcription:** Whisper can drop digits, mishear words, and garble Tagalog or Taglish. A missed urgent word means the call is not escalated by keyword, so the queue depends on the transcript being right.
- **Keyword list:** the urgent list is a safety net, not a complete list of emergencies. Keep it broad, and accept false alarms.
- **Draft review:** a person must read each draft and check the number and name before sending.
- **Stale queue:** the queue reflects the last run. Check the timestamp at the top before acting on it.

## Privacy

Voicemail recordings and transcripts contain personal and health information. Before any real use:

- Tell callers that voicemails may be recorded and transcribed.
- Set a retention period, and delete audio and transcripts on schedule.
- Review data terms for every service in the chain, including the transcription and AI providers.
- Confirm the arrangement against the Data Privacy Act of 2012 (RA 10173) and current guidance from the National Privacy Commission. This README is not legal advice.

Never commit recordings, transcripts, the answer key, or `output/`. The `.gitignore` excludes them, but check with `git status` before every push.

## Status

This is a prototype for supervised testing. It is not connected to a live phone line and should not be used as an automated receptionist or as the only route for emergency calls.

## Tools

Python, OpenAI Whisper for transcription, the Anthropic API (Claude Haiku) for extraction, and Claude Code for development.
