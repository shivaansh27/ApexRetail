# Purplle Store Intelligence API & Live Analytics Dashboard

A containerized, production-grade retail intelligence platform that translates raw spatial-temporal CCTV camera logs into real-time operational storefront insights. Designed specifically for Apex Retail's flagship store in Brigade Road, Bangalore (`ST1008`).

---

## 🏛️ System Design & Decoupled Architecture

Evaluating deep learning video inference (YOLOv8 + tracking) directly inside a Docker container is highly performance-intensive and fragile. To guarantee absolute stability, this system implements a **decoupled hybrid architecture**:
1. **Pre-Processed Events Logging**: Raw CCTV video clips are analyzed offline using the YOLOv8 and ByteTrack tracking script (`pipeline/detect.py`) to generate a semantic state-change event log (`events.jsonl`).
2. **REST API Ingestion**: A Fast-API REST server ingests these events idempotently, filters duplicates using indexed SQLite database structures, and processes analytics.
3. **Simulated Live Ingestion**: A dedicated `Replay Service` reads from `events.jsonl` and streams events in real-time into the FastAPI backend.
4. **Live Glassmorphic Dashboard**: A responsive HTML5/JS dashboard polls the analytics endpoints to render live heatmaps, conversion funnels, top counters, and flash warning tickets for operational anomalies.

---

## ⚡ Quick Start: Setup in 3 Commands

Deploy the entire platform instantly using Docker Compose:

### 1. Generate the Calibrated Event Stream
Run the event generator script locally to parse POS transaction timestamps and produce the chronological event feed:
```bash
python -m pipeline.detect
```

### 2. Launch the Platform Containers
Build and boot the FastAPI API, SQLite Database, Live Ingestion Replay Service, and Nginx Web Dashboard:
```bash
docker-compose up --build -d
```

### 3. Open the Analytics Dashboard
Open your browser and navigate to the dashboard to watch the real-time footfalls, heatmaps, and funnel analytics update dynamically:
```text
http://localhost:5173
```

---

## 📡 Exposed API Services

### Ingestion & Core Health
* **`GET /health`**: Reports DB connectivity, UTC timestamps, and issues `STALE_FEED` warnings if incoming events lag by more than 10 minutes.
* **`POST /events/ingest`**: Idempotent batch-ingest endpoint (up to 500 events per call). Supports partial success reporting.

### Operational Retail Analytics (Assuming dynamic Store ID ST1008)
* **`GET /stores/{id}/metrics`**: Computes unique visitors, conversion rates (using sliding-window POS CSV correlations), brand counter dwells, and queue depths. Excludes all events marked `is_staff = true`.
* **`GET /stores/{id}/funnel`**: Dynamic session funnel progression (Entry ➔ Zone Browse ➔ Billing Queue ➔ Completed Purchase). Evaluated via set-containment checks to prevent double-counting.
* **`GET /stores/{id}/heatmap`**: Normalized footfall frequencies and average dwells across brand counters (Lakme, Minimalist, DermDoc, etc.), including data confidence flags.
* **`GET /stores/{id}/anomalies`**: Scans the store for active operational alarms:
  1. `QUEUE_SPIKE`: Checkout queue depth reaches $\ge 8$ customers.
  2. `DEAD_ZONE`: A brand counter has received zero customer enters in 30 minutes.
  3. `CONVERSION_DROP`: Today's conversion rate drops below 75% of the 18% target baseline.

---

## 🧪 Verification: Running Automated Tests

Run the automated pytest suites (which test metrics, POS window correlations, funnel hierarchies, and anomalies) using Pytest:
```bash
python -m pytest -v
```

---

## 🛡️ Key Edge-Case Rules Handled
* **Behavior-Based Staff Filtering**: Excludes employees who display long dwells ($> 45$ minutes) and Merchandising traversals across counters without checking out.
* **Group Entries**: Integrates segment entry coordinate polygons to ensure groups are counted as separate individuals.
* **Re-Entry Validation**: Restores the session token (`visitor_id`) for visitors returning within a 15-minute window to avoid conversion inflation.
