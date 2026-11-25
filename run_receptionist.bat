@echo off
cd /d D:\PythonProject\ai-voice-receptionist
call ..\.venv\Scripts\activate
python -m src.transcribe >> output\run.log 2>&1
python -m src.main >> output\run.log 2>&1