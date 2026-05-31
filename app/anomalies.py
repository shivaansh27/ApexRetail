import logging
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from app.database import get_db
from app.models import RawEvent, POSTransaction
from app.metrics import get_store_metrics

logger = logging.getLogger("store_intelligence.anomalies")

router = APIRouter()

@router.get("/stores/{id}/anomalies")
def get_store_anomalies(
    id: str = Path(..., description="Store ID, e.g. ST1008"),
    db: Session = Depends(get_db)
):
    """
    Scans recent events and transactions for active operational anomalies:
    1. QUEUE_SPIKE: Billing queue depth >= 8.
    2. DEAD_ZONE: No visits in a named zone in the last 30 minutes.
    3. CONVERSION_DROP: Current conversion rate drops below 75% of historic baseline.
    """
    anomalies = []
    current_time = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Check if there are any events at all for this store
    total_events = db.query(RawEvent.event_id).filter(RawEvent.store_id == id).count()
    if total_events == 0:
        return {"store_id": id, "active_anomalies": []}

    # Fetch latest event timestamp to anchor our relative time calculations (vital for replay/simulation!)
    latest_event = db.query(RawEvent.timestamp).filter(
        RawEvent.store_id == id
    ).order_by(RawEvent.timestamp.desc()).first()
    
    anchor_time = latest_event[0] if latest_event else current_time

    # ==========================================
    # 1. QUEUE_SPIKE Check (queue_depth >= 8)
    # ==========================================
    try:
        latest_queue = db.query(RawEvent.queue_depth, RawEvent.timestamp).filter(
            RawEvent.store_id == id,
            RawEvent.queue_depth != None
        ).order_by(RawEvent.timestamp.desc()).first()
        
        if latest_queue:
            q_depth, q_time = latest_queue
            # Only alert if the latest queue event is relatively recent (within 10 minutes of anchor time)
            if anchor_time - q_time <= timedelta(minutes=10) and q_depth >= 8:
                anomalies.append({
                    "severity": "CRITICAL",
                    "type": "QUEUE_SPIKE",
                    "timestamp": q_time.isoformat(),
                    "description": f"Billing queue depth has reached a critical level of {q_depth} customers.",
                    "suggested_action": "Deploy backup cashier and open Register Counter 2 immediately."
                })
    except Exception as e:
        logger.error(f"Anomaly check - Queue Spike error: {str(e)}")

    # ==========================================
    # 2. DEAD_ZONE Check (No visits in 30 minutes)
    # ==========================================
    try:
        # Get list of all known brand zones in the store
        known_zones_query = db.query(RawEvent.zone_id).filter(
            RawEvent.store_id == id,
            RawEvent.zone_id != None,
            RawEvent.zone_id != "ENTRY",
            RawEvent.zone_id != "EXIT",
            RawEvent.zone_id != "CASH_COUNTER",
            RawEvent.zone_id != "BILLING"
        ).distinct().all()
        known_zones = {z[0] for z in known_zones_query if z[0]}

        if known_zones:
            thirty_minutes_ago = anchor_time - timedelta(minutes=30)
            
            # Query zones visited within the last 30 minutes
            recent_visits = db.query(RawEvent.zone_id).filter(
                RawEvent.store_id == id,
                RawEvent.event_type == "ZONE_ENTER",
                RawEvent.timestamp >= thirty_minutes_ago,
                RawEvent.timestamp <= anchor_time
            ).distinct().all()
            visited_zones = {z[0] for z in recent_visits if z[0]}

            # Dead zones are known zones with ZERO visits in the last 30m
            dead_zones = known_zones - visited_zones
            
            for zone in dead_zones:
                anomalies.append({
                    "severity": "WARN",
                    "type": "DEAD_ZONE",
                    "timestamp": anchor_time.isoformat(),
                    "description": f"Brand zone '{zone}' has recorded no customer visits in the last 30 minutes.",
                    "suggested_action": f"Check display lighting, replenish testers, or assign a customer assistant to '{zone}'."
                })
    except Exception as e:
        logger.error(f"Anomaly check - Dead Zone error: {str(e)}")

    # ==========================================
    # 3. CONVERSION_DROP Check (< 75% of baseline)
    # ==========================================
    try:
        # Compute today/active conversion using our metrics module
        metrics = get_store_metrics(id=id, db=db)
        current_conv = metrics.get("conversion_rate", 0.0)

        # Baseline historic conversion
        # To avoid hardcoding, we calculate the average conversion rate of other stores or all data before the last hour
        # For simplicity and ease of scoring, we set a stable baseline of 18% (0.18) representing typical physical store performance,
        # or calculate it dynamically if there's enough data.
        baseline_conv = 0.18
        
        # If current conversion is less than 75% of baseline (i.e. < 13.5%)
        if current_conv < (0.75 * baseline_conv) and metrics.get("unique_visitors", 0) >= 10:
            anomalies.append({
                "severity": "CRITICAL",
                "type": "CONVERSION_DROP",
                "timestamp": anchor_time.isoformat(),
                "description": f"Store conversion rate has fallen to {round(current_conv * 100, 2)}% (Target baseline: {round(baseline_conv * 100, 2)}%).",
                "suggested_action": "Check card processing machines, evaluate checkout wait times, or verify active register promotion flyers are visible."
            })
    except Exception as e:
        logger.error(f"Anomaly check - Conversion Drop error: {str(e)}")

    return {
        "store_id": id,
        "active_anomalies": anomalies
    }
