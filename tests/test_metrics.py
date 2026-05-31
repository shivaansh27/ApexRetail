# PROMPT: Create an automated pytest suite for checking FastAPI store metrics, conversion rates, and session funnels. Use SQLAlchemy with a shared, isolated in-memory SQLite database (using StaticPool to preserve tables across connections). Simulate non-staff entry events, zone dwells, and billing queue joins. Verify that conversion rates are calculated within a 5-minute pre-transaction POS correlation window, and funnel stages adhere to set containment containment counts (Entry >= Zone >= Queue >= Purchase). Include duplicate event checking.
# CHANGES MADE: Customized baseline assertions to use StaticPool for high-reliability, zero-config in-memory SQLite database isolation. Added structured test setup fixtures.

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

@pytest.fixture(scope="function", autouse=True)
def setup_db():
    # Pre-seed transactions in test database
    db = TestingSessionLocal()
    try:
        # Transaction at 15:00:00
        txn = POSTransaction(
            transaction_id="TXN_TEST_001",
            store_id="ST_TEST",
            timestamp=datetime(2026, 4, 10, 15, 0, 0),
            basket_value_inr=500.0,
            qty=1,
            customer_name="Alice"
        )
        db.add(txn)
        db.commit()
    finally:
        db.close()
        
    yield

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("OK", "WARN")
    assert data["database"] == "connected"

def test_events_ingest_and_idempotency():
    # 1. Ingest an event
    payload = [{
        "event_id": "test-uuid-001",
        "store_id": "ST_TEST",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_TEST_1",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T14:45:00Z",
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.95,
        "metadata": {
            "queue_depth": None,
            "sku_zone": None,
            "session_seq": 1
        }
    }]
    
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["inserted"] == 1
    assert data["skipped"] == 0
    assert len(data["errors"]) == 0

    # 2. Ingest duplicate event to assert IDEMPOTENCY
    response = client.post("/events/ingest", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["inserted"] == 0
    assert data["skipped"] == 1 # Skipped successfully
    assert len(data["errors"]) == 0

def test_metrics_conversion_and_funnels():
    # Seed events for a visitor session:
    # VIS_TEST_1 enters at 14:45:00, joins billing queue at 14:57:00 (which is within 5 minutes before transaction at 15:00:00), exits at 15:05:00
    events = [
        # ENTRY
        {
            "event_id": "evt-001", "store_id": "ST_TEST", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_TEST_1",
            "event_type": "ENTRY", "timestamp": "2026-04-10T14:45:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": False, "confidence": 0.99, "metadata": {"session_seq": 1}
        },
        # ZONE_ENTER
        {
            "event_id": "evt-002", "store_id": "ST_TEST", "camera_id": "CAM_FLOOR", "visitor_id": "VIS_TEST_1",
            "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T14:46:00Z", "zone_id": "MINIMALIST", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.95, "metadata": {"session_seq": 2}
        },
        # ZONE_DWELL
        {
            "event_id": "evt-003", "store_id": "ST_TEST", "camera_id": "CAM_FLOOR", "visitor_id": "VIS_TEST_1",
            "event_type": "ZONE_DWELL", "timestamp": "2026-04-10T14:55:00Z", "zone_id": "MINIMALIST", "dwell_ms": 540000,
            "is_staff": False, "confidence": 0.95, "metadata": {"session_seq": 3}
        },
        # BILLING_QUEUE_JOIN (within 5m of transaction at 15:00:00)
        {
            "event_id": "evt-004", "store_id": "ST_TEST", "camera_id": "CAM_BILLING", "visitor_id": "VIS_TEST_1",
            "event_type": "BILLING_QUEUE_JOIN", "timestamp": "2026-04-10T14:57:00Z", "zone_id": "CASH_COUNTER", "dwell_ms": 0,
            "is_staff": False, "confidence": 0.99, "metadata": {"queue_depth": 3, "session_seq": 4}
        },
        # EXIT
        {
            "event_id": "evt-005", "store_id": "ST_TEST", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_TEST_1",
            "event_type": "EXIT", "timestamp": "2026-04-10T15:05:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": False, "confidence": 0.99, "metadata": {"session_seq": 5}
        }
    ]
    
    # Ingest seed events
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    assert r.json()["inserted"] == 5

    # 1. Verify metrics endpoint
    r_metrics = client.get("/stores/ST_TEST/metrics")
    assert r_metrics.status_code == 200
    metrics_data = r_metrics.json()
    assert metrics_data["unique_visitors"] == 1
    assert metrics_data["conversion_rate"] == 1.0 # 1 out of 1 visitors converted
    assert metrics_data["avg_dwell_per_zone"]["MINIMALIST"] == 540000
    assert metrics_data["current_queue_depth"] == 3

    # 2. Verify funnel endpoint
    r_funnel = client.get("/stores/ST_TEST/funnel")
    assert r_funnel.status_code == 200
    funnel_data = r_funnel.json()
    stages = funnel_data["stages"]
    assert stages["1_entry"]["count"] == 1
    assert stages["2_zone_visit"]["count"] == 1
    assert stages["3_billing_queue"]["count"] == 1
    assert stages["4_purchase"]["count"] == 1

    # 3. Verify heatmap normalization
    r_heatmap = client.get("/stores/ST_TEST/heatmap")
    assert r_heatmap.status_code == 200
    heatmap_data = r_heatmap.json()
    assert heatmap_data["zones"]["MINIMALIST"]["raw_frequency"] == 1
    assert heatmap_data["zones"]["MINIMALIST"]["intensity_score"] == 100.0
