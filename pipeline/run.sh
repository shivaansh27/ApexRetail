#!/bin/bash
# One-command entrypoint to process clips / seed event database and start streaming.
set -e

echo "=== Purplle Store Intelligence - Pipeline Controller ==="

# 1. Check if events.jsonl exists. If not, generate it from the POS CSV
if [ ! -f "events.jsonl" ]; then
    echo "events.jsonl not found. Generating calibrated event stream from POS logs..."
    python -m pipeline.detect
else
    echo "Using existing events.jsonl data feed."
fi

# 2. Run the real-time event replay streamer
echo "Starting real-time Event Replay Streamer..."
python pipeline/event_replay.py
