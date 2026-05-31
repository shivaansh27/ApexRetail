from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import RawEvent, POSTransaction

router = APIRouter()

@router.get("/stores/{id}/funnel")
def get_store_funnel(
    id: str = Path(..., description="Store ID, e.g. ST1008"),
    db: Session = Depends(get_db)
):
    """
    Returns session-based funnel analytics: Entry -> Zone Visit -> Billing Queue -> Purchase.
    Deduplicates sessions dynamically so re-entries do not double-count a visitor.
    """
    try:
        # 1. Base Stage: ENTRY
        entry_records = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            RawEvent.event_type == "ENTRY"
        ).distinct().all()
        entry_set = {r[0] for r in entry_records}
        
        # If no entries, all funnel counts are zero
        if not entry_set:
            return {
                "store_id": id,
                "stages": {
                    "1_entry": {"count": 0, "percentage": 100.0, "drop_off_pct": 0.0},
                    "2_zone_visit": {"count": 0, "percentage": 0.0, "drop_off_pct": 0.0},
                    "3_billing_queue": {"count": 0, "percentage": 0.0, "drop_off_pct": 0.0},
                    "4_purchase": {"count": 0, "percentage": 0.0, "drop_off_pct": 0.0}
                }
            }

        # 2. Zone Stage: ZONE_ENTER / ZONE_DWELL
        zone_records = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            (RawEvent.event_type == "ZONE_ENTER") | (RawEvent.event_type == "ZONE_DWELL")
        ).distinct().all()
        zone_raw_set = {r[0] for r in zone_records}

        # 3. Queue Stage: BILLING_QUEUE_JOIN / CASH_COUNTER
        queue_records = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            (RawEvent.event_type == "BILLING_QUEUE_JOIN") |
            (RawEvent.zone_id == "CASH_COUNTER") |
            (RawEvent.zone_id == "BILLING")
        ).distinct().all()
        queue_raw_set = {r[0] for r in queue_records}

        # 4. Purchase Stage: Converted Visitors (POS transaction correlation)
        purchase_set = set()
        transactions = db.query(POSTransaction.timestamp).filter(POSTransaction.store_id == id).all()
        txn_timestamps = [t[0] for t in transactions]

        if txn_timestamps:
            billing_events = db.query(RawEvent.visitor_id, RawEvent.timestamp).filter(
                RawEvent.store_id == id,
                RawEvent.is_staff == False,
                (RawEvent.event_type == "BILLING_QUEUE_JOIN") | 
                (RawEvent.event_type == "BILLING_QUEUE_ABANDON") |
                (RawEvent.zone_id == "CASH_COUNTER") |
                (RawEvent.zone_id == "BILLING")
            ).all()

            for txn_ts in txn_timestamps:
                window_start = txn_ts - timedelta(minutes=5)
                for visitor_id, event_ts in billing_events:
                    if window_start <= event_ts <= txn_ts:
                        if visitor_id in entry_set:
                            purchase_set.add(visitor_id)

        # Enforce mathematical hierarchy (Set inclusion containment)
        # Purchase -> must have queued -> must have explored zones -> must have entered
        final_purchase_set = purchase_set & entry_set
        final_queue_set = (queue_raw_set | final_purchase_set) & entry_set
        final_zone_set = (zone_raw_set | final_queue_set) & entry_set
        final_entry_set = entry_set

        entry_count = len(final_entry_set)
        zone_count = len(final_zone_set)
        queue_count = len(final_queue_set)
        purchase_count = len(final_purchase_set)

        # Compute funnel conversion percentages (out of entry baseline)
        pct_entry = 100.0
        pct_zone = round((zone_count / entry_count) * 100, 2) if entry_count > 0 else 0.0
        pct_queue = round((queue_count / entry_count) * 100, 2) if entry_count > 0 else 0.0
        pct_purchase = round((purchase_count / entry_count) * 100, 2) if entry_count > 0 else 0.0

        # Compute stage-to-stage drop-off percentages
        drop_entry_to_zone = round(((entry_count - zone_count) / entry_count) * 100, 2) if entry_count > 0 else 0.0
        drop_zone_to_queue = round(((zone_count - queue_count) / zone_count) * 100, 2) if zone_count > 0 else 0.0
        drop_queue_to_purchase = round(((queue_count - purchase_count) / queue_count) * 100, 2) if queue_count > 0 else 0.0

        return {
            "store_id": id,
            "stages": {
                "1_entry": {
                    "count": entry_count,
                    "percentage": pct_entry,
                    "drop_off_pct": 0.0
                },
                "2_zone_visit": {
                    "count": zone_count,
                    "percentage": pct_zone,
                    "drop_off_pct": drop_entry_to_zone
                },
                "3_billing_queue": {
                    "count": queue_count,
                    "percentage": pct_queue,
                    "drop_off_pct": drop_zone_to_queue
                },
                "4_purchase": {
                    "count": purchase_count,
                    "percentage": pct_purchase,
                    "drop_off_pct": drop_queue_to_purchase
                }
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error on funnel calculation: {str(e)}")
