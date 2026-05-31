import os
import json
import time
import requests
import logging

# Configure pipeline logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("store_intelligence.pipeline.event_replay")

API_URL = os.environ.get("API_URL", "http://localhost:8000")
EVENTS_PATH = os.environ.get("EVENTS_PATH", "events.jsonl")
REPLAY_DELAY = float(os.environ.get("REPLAY_DELAY", "0.2")) # Delay in seconds between events
LOOP_INFINITELY = os.environ.get("LOOP_INFINITELY", "true").lower() == "true"

def wait_for_api():
    """
    Blocks until the FastAPI backend is healthy and responding.
    """
    health_url = f"{API_URL}/health"
    logger.info(f"Waiting for API at {health_url} to become ready...")
    while True:
        try:
            r = requests.get(health_url, timeout=3)
            if r.status_code == 200:
                logger.info("FastAPI Backend is healthy, active, and ready!")
                break
        except Exception:
            pass
        time.sleep(1)

def send_batch(ingest_url, batch, headers):
    try:
        response = requests.post(ingest_url, json=batch, headers=headers, timeout=10)
        if response.status_code == 200:
            res = response.json()
            inserted = res.get("inserted", 0)
            skipped = res.get("skipped", 0)
            errors = res.get("errors", [])
            logger.info(
                f"Simulated Ingest: Sent batch of {len(batch)} events. "
                f"Result: {inserted} inserted, {skipped} skipped, {len(errors)} errors."
            )
            if errors:
                logger.warning(f"Some events in batch had errors: {errors[:5]}")
        else:
            logger.error(f"Failed to ingest event batch: Status {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"Error during event batch ingestion: {str(e)}")

def run_replay():
    # Attempt local relative search first, then expand
    path_candidates = [
        EVENTS_PATH,
        "events.jsonl",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "events.jsonl")
    ]
    
    events_file = None
    for candidate in path_candidates:
        if os.path.exists(candidate):
            events_file = candidate
            break

    if not events_file:
        logger.error(f"Could not locate events.jsonl file inside search candidates. Exiting Replay Service.")
        return

    logger.info(f"Targeting active event log file: {events_file}")
    wait_for_api()

    ingest_url = f"{API_URL}/events/ingest"
    logger.info(f"Starting simulated real-time event ingestion to: {ingest_url}")

    # Retrieve optional ingestion API key
    headers = {}
    ingest_api_key = os.environ.get("INGESTION_API_KEY")
    if ingest_api_key:
        headers["X-API-Key"] = ingest_api_key
        logger.info("Configured X-API-Key header for event ingestion.")

    batch_size = int(os.environ.get("BATCH_SIZE", "50"))

    while True:
        with open(events_file, "r", encoding="utf-8") as f:
            batch = []
            for line in f:
                if not line.strip():
                    continue
                try:
                    event_data = json.loads(line)
                    batch.append(event_data)
                except Exception as e:
                    logger.error(f"Error parsing event line: {str(e)}")
                    continue
                
                if len(batch) >= batch_size:
                    send_batch(ingest_url, batch, headers)
                    batch = []
                    time.sleep(REPLAY_DELAY)
            
            if batch:
                send_batch(ingest_url, batch, headers)
                time.sleep(REPLAY_DELAY)
        
        if not LOOP_INFINITELY:
            logger.info("Completed replaying events.jsonl. Exiting Replay Service.")
            break
        else:
            logger.info("Reached end of events.jsonl. Re-looping ingestion feed in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    run_replay()
