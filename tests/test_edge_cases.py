# PROMPT: Create an automated pytest suite for checking edge cases of the FastAPI Store Intelligence endpoints. Test empty or unknown stores to ensure zeroed metrics and no crashes. Test that all-staff events are excluded from visitor counts. Test that zero POS transactions yield a conversion rate of 0.0. Test that reentry events do not double-count in the session funnel. Test that batches exceeding 500 events return HTTP 400 Bad Request. Test partial success ingestion with mixed valid and invalid events. Test that the CONVERSION_DROP anomaly triggers correctly under low conversion rates with at least 10 unique visitors. Use StaticPool in-memory SQLite for complete isolation.
# CHANGES MADE: Developed comprehensive edge-case test suite covering Pydantic validation boundaries, data isolation, and specific business intelligence anomaly threshold triggers.

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Base, RawEvent, POSTransaction
from conftest import TestingSessionLocal

client = TestClient(app)

def test_empty_or_unknown_store():
    # Test that querying a totally non-existent store ID returns empty/zeroed results and never crashes
    store_id = "STORE_UNKNOWN_999"
    
    # 1. Metrics
    r = client.get(f"/stores/{store_id}/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["current_queue_depth"] == 0
    assert data["avg_dwell_per_zone"] == {}
    
    # 2. Funnel
    r = client.get(f"/stores/{store_id}/funnel")
    assert r.status_code == 200
    data = r.json()
    assert data["stages"]["1_entry"]["count"] == 0
    assert data["stages"]["4_purchase"]["count"] == 0
    
    # 3. Heatmap
    r = client.get(f"/stores/{store_id}/heatmap")
    assert r.status_code == 200
    data = r.json()
    assert data["zones"] == {}
    
    # 4. Anomalies
    r = client.get(f"/stores/{store_id}/anomalies")
    assert r.status_code == 200
    data = r.json()
    assert len(data["active_anomalies"]) == 0


def test_all_staff_events_excluded():
    # Seed only events where is_staff is True
    events = [
        {
            "event_id": "staff-001", "store_id": "ST_STAFF", "camera_id": "CAM_ENTRY", "visitor_id": "STAFF_01",
            "event_type": "ENTRY", "timestamp": "2026-04-10T14:00:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": True, "confidence": 0.99, "metadata": {"session_seq": 1}
        },
        {
            "event_id": "staff-002", "store_id": "ST_STAFF", "camera_id": "CAM_FLOOR", "visitor_id": "STAFF_01",
            "event_type": "ZONE_ENTER", "timestamp": "2026-04-10T14:01:00Z", "zone_id": "MINIMALIST", "dwell_ms": 0,
            "is_staff": True, "confidence": 0.99, "metadata": {"session_seq": 2}
        }
    ]
    
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    assert r.json()["inserted"] == 2
    
    # Check that visitor metrics are 0 because they are all staff
    r_metrics = client.get("/stores/ST_STAFF/metrics")
    assert r_metrics.status_code == 200
    assert r_metrics.json()["unique_visitors"] == 0
    
    # Check funnel has 0 entries
    r_funnel = client.get("/stores/ST_STAFF/funnel")
    assert r_funnel.json()["stages"]["1_entry"]["count"] == 0


def test_zero_pos_transactions():
    # Ingest 1 visitor but no transactions seeded for ST_ZERO_TXN
    events = [{
        "event_id": "zero-txn-evt", "store_id": "ST_ZERO_TXN", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_1",
        "event_type": "ENTRY", "timestamp": "2026-04-10T14:00:00Z", "zone_id": None, "dwell_ms": 0,
        "is_staff": False, "confidence": 0.99, "metadata": {"session_seq": 1}
    }]
    
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    
    # Verify metrics show 1 visitor but 0.0 conversion rate
    r_metrics = client.get("/stores/ST_ZERO_TXN/metrics")
    assert r_metrics.status_code == 200
    data = r_metrics.json()
    assert data["unique_visitors"] == 1
    assert data["conversion_rate"] == 0.0


def test_reentry_event_no_double_count_in_funnel():
    # Send multiple entry events for the same visitor session
    events = [
        {
            "event_id": "reentry-001", "store_id": "ST_REENTRY", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_DUP",
            "event_type": "ENTRY", "timestamp": "2026-04-10T14:00:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": False, "confidence": 0.99, "metadata": {"session_seq": 1}
        },
        {
            "event_id": "reentry-002", "store_id": "ST_REENTRY", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_DUP",
            "event_type": "ENTRY", "timestamp": "2026-04-10T14:15:00Z", "zone_id": None, "dwell_ms": 0,
            "is_staff": False, "confidence": 0.99, "metadata": {"session_seq": 2}
        }
    ]
    
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    
    # Verify unique visitors count is 1
    r_metrics = client.get("/stores/ST_REENTRY/metrics")
    assert r_metrics.json()["unique_visitors"] == 1
    
    # Verify funnel entry is 1
    r_funnel = client.get("/stores/ST_REENTRY/funnel")
    assert r_funnel.json()["stages"]["1_entry"]["count"] == 1


def test_batch_size_limit_breached():
    # Create payload of 501 events
    huge_payload = []
    for i in range(501):
        huge_payload.append({
            "event_id": f"huge-evt-{i}",
            "store_id": "ST_LIMIT",
            "camera_id": "CAM_ENTRY",
            "visitor_id": f"VIS_H_{i}",
            "event_type": "ENTRY",
            "timestamp": "2026-04-10T14:00:00Z",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95
        })
        
    r = client.post("/events/ingest", json=huge_payload)
    assert r.status_code == 400
    assert "exceeds the limit of 500" in r.json()["detail"]


def test_partial_success_mixed_events():
    # Ingest 1 valid event and 1 completely invalid event (missing visitor_id, event_type)
    payload = [
        {
            "event_id": "valid-part-001", "store_id": "ST_PARTIAL", "camera_id": "CAM_ENTRY", "visitor_id": "VIS_VALID",
            "event_type": "ENTRY", "timestamp": "2026-04-10T14:00:00Z", "dwell_ms": 0, "is_staff": False, "confidence": 0.99
        },
        {
            "event_id": "invalid-part-002", "store_id": "ST_PARTIAL", "camera_id": "CAM_ENTRY"
            # Missing critical validation fields
        }
    ]
    
    r = client.post("/events/ingest", json=payload)
    assert r.status_code == 200
    res = r.json()
    assert res["inserted"] == 1
    assert len(res["errors"]) == 1
    assert res["errors"][0]["event_id"] == "invalid-part-002"
    
    # Ingest completely invalid batch (must return 400)
    invalid_payload = [
        {"event_id": "inv-1"},
        {"event_id": "inv-2"}
    ]
    r_bad = client.post("/events/ingest", json=invalid_payload)
    assert r_bad.status_code == 400
    assert "failed structural validation" in r_bad.json()["detail"]["message"]


def test_conversion_drop_anomaly():
    # To trigger CONVERSION_DROP:
    # 1. Ingest entry events for 10 unique non-staff visitors
    events = []
    for i in range(10):
        events.append({
            "event_id": f"conv-drop-evt-{i}",
            "store_id": "ST_CONV_DROP",
            "camera_id": "CAM_ENTRY",
            "visitor_id": f"VIS_CD_{i}",
            "event_type": "ENTRY",
            "timestamp": f"2026-04-10T14:{10+i:02d}:00Z",
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {"session_seq": 1}
        })
    
    r = client.post("/events/ingest", json=events)
    assert r.status_code == 200
    
    # 2. Add 0 POS transactions for this store (conversion rate = 0.0%)
    # Since current_conv (0.0) is < 75% of baseline (18% baseline * 0.75 = 13.5%) and unique_visitors is >= 10,
    # CONVERSION_DROP anomaly must trigger!
    
    r_anom = client.get("/stores/ST_CONV_DROP/anomalies")
    assert r_anom.status_code == 200
    data = r_anom.json()
    
    active = data["active_anomalies"]
    drop_anoms = [a for a in active if a["type"] == "CONVERSION_DROP"]
    assert len(drop_anoms) == 1
    assert drop_anoms[0]["severity"] == "CRITICAL"
    assert "card processing machines" in drop_anoms[0]["suggested_action"]
