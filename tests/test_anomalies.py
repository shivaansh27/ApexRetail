# PROMPT: Create an automated pytest suite for checking FastAPI store anomalies. Simulate events to trigger QUEUE_SPIKE (queue_depth >= 8) and DEAD_ZONE (no zone enter events in the last 30 minutes). Assert the correct anomaly severity values (CRITICAL, WARN, INFO) and suggested action response fields. Use SQLAlchemy with a shared, isolated in-memory SQLite database (using StaticPool to preserve tables across connections).
# CHANGES MADE: Configured testing suite to utilize StaticPool in-memory SQLite database to avoid directory file leakage and ensure strict connection isolation in pytest runs.

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import get_db
from app.models import Base, RawEvent, POSTransaction

from conftest import TestingSessionLocal

client = TestClient(app)

def test_queue_spike_anomaly():
    # Ingest a normal ENTRY and then a BILLING_QUEUE_JOIN with queue_depth = 9 (>= 8)
    events = [
        {
            "event_id": "normal-evt-001", "store_id": "ST_ANOMALY", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_A_1",
            "event_type": "ENTRY", "timestamp": "2026-04-10T16:00:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": False, "confidence": 0.95, "metadata": {"session_seq": 1}
        },
        {
            "event_id": "normal-evt-002", "store_id": "ST_ANOMALY", "camera_id": "CAM_BILLING", "visitor_id": "VIS_A_1",
            "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-04-10T16:05:00Z", "zone_id": "CASH_COUNTER", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.95, "metadata": {"queue_depth": 9, "session_seq": 2} # Spike!
        }
    ]

    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200

    r_anom = client.get("/stores/ST_ANOMALY/anomalies")
    assert r_anom.status_code == 200
    data = r_anom.json()
    
    # Assert QUEUE_SPIKE triggered
    active = data["active_anomalies"]
    queue_spikes = [a for a in active if a["type"] == "QUEUE_SPIKE"]
    assert len(queue_spikes) == 1
    assert queue_spikes[0]["severity"] == "CRITICAL"
    assert "Register Counter 2" in queue_spikes[0]["suggested_action"]

def test_dead_zone_anomaly():
    # Ingest historical visits in the store, but NO entries in a specific zone (e.g. "GOOD_VIBES") in the last 30 minutes
    # Target zones are: MINIMALIST (visited recently) and GOOD_VIBES (not visited recently)
    events = [
        # Visited MINIMALIST 5 minutes ago (active)
        {
            "event_id": "active-evt-001", "store_id": "ST_ANOMALY", "camera_id": "CAM_FLOOR", "visitor_id": "VIS_A_2",
            "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T16:25:00Z", "zone_id": "MINIMALIST", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.95, "metadata": {"session_seq": 1}
        },
        # Visited GOOD_VIBES 1 hour ago (inactive / dead zone candidate)
        {
            "event_id": "old-evt-001", "store_id": "ST_ANOMALY", "camera_id": "CAM_FLOOR", "visitor_id": "VIS_A_3",
            "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T15:00:00Z", "zone_id": "GOOD_VIBES", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.95, "metadata": {"session_seq": 1}
        }
    ]

    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200

    r_anom = client.get("/stores/ST_ANOMALY/anomalies")
    assert r_anom.status_code == 200
    data = r_anom.json()
    
    # Assert GOOD_VIBES flagged as DEAD_ZONE
    active = data["active_anomalies"]
    dead_zones = [a for a in active if a["type"] == "DEAD_ZONE" and "GOOD_VIBES" in a["description"]]
    assert len(dead_zones) == 1
    assert dead_zones[0]["severity"] == "WARN"
