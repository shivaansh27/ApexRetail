# One-command Powershell runner for Windows environments
Write-Host "=== Purplle Store Intelligence - Pipeline Controller (Windows) ===" -ForegroundColor Cyan

$events_file = "events.jsonl"

# 1. Check if events.jsonl exists. If not, generate it from the POS CSV
if (-not (Test-Path $events_file)) {
    Write-Host "events.jsonl not found. Generating calibrated event stream from POS logs..." -ForegroundColor Yellow
    $env:PYTHONPATH="."
    python -m pipeline.detect
} else {
    Write-Host "Using existing events.jsonl data feed." -ForegroundColor Green
}

# 2. Run the real-time event replay streamer
Write-Host "Starting real-time Event Replay Streamer..." -ForegroundColor Green
python pipeline/event_replay.py
