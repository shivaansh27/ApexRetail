import logging
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app.database import get_db
from app.models import RawEvent, POSTransaction

logger = logging.getLogger("store_intelligence.metrics")

router = APIRouter()

@router.get("/stores/{id}/metrics")
def get_store_metrics(
    id: str = Path(..., description="Store ID, e.g. ST1008"),
    db: Session = Depends(get_db)
):
    """
    Returns real-time store analytics: unique visitors, conversion rate, 
    average dwell per zone, queue depth, and abandonment rate.
    """
    # 1. Total Unique Non-Staff Visitors (who have registered an ENTRY)
    try:
        unique_visitors_query = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            RawEvent.event_type == "ENTRY"
        ).distinct()
        unique_visitor_ids = {r[0] for r in unique_visitors_query.all()}
        unique_visitors_count = len(unique_visitor_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error on unique visitors: {str(e)}")

    # If no visitors have entered, metrics are zeroed
    if unique_visitors_count == 0:
        return {
            "store_id": id,
            "unique_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_per_zone": {},
            "current_queue_depth": 0,
            "abandonment_rate": 0.0
        }

    # 2. Conversion Rate via POS Correlation
    # "A visitor who was in the billing zone in the 5-minute window before a transaction timestamp counts as a converted visitor for that session."
    try:
        # Fetch all transactions for this store
        transactions = db.query(POSTransaction.timestamp).filter(
            POSTransaction.store_id == id
        ).all()
        txn_timestamps = [t[0] for t in transactions]

        converted_visitors = set()

        if txn_timestamps:
            # Query all billing events for non-staff visitors
            # Billing zones can be represented by zone_id="CASH_COUNTER", "BILLING" or event_type="BILLING_QUEUE_JOIN"
            billing_events = db.query(RawEvent.visitor_id, RawEvent.timestamp).filter(
                RawEvent.store_id == id,
                RawEvent.is_staff == False,
                (RawEvent.event_type == "BILLING_QUEUE_JOIN") | 
                (RawEvent.event_type == "BILLING_QUEUE_ABANDON") |
                (RawEvent.zone_id == "CASH_COUNTER") |
                (RawEvent.zone_id == "BILLING")
            ).all()

            # For each transaction, find visitors who were at billing in the [t-5m, t] window
            for txn_ts in txn_timestamps:
                window_start = txn_ts - timedelta(minutes=5)
                for visitor_id, event_ts in billing_events:
                    if window_start <= event_ts <= txn_ts:
                        # Ensure this visitor was actually in the store's unique visitor list
                        if visitor_id in unique_visitor_ids:
                            converted_visitors.add(visitor_id)

        conversion_rate = len(converted_visitors) / unique_visitors_count
    except Exception as e:
        conversion_rate = 0.0
        logger.error(f"Error calculating conversion rate: {str(e)}")

    # 3. Average Dwell Per Zone
    try:
        dwell_results = db.query(
            RawEvent.zone_id,
            func.avg(RawEvent.dwell_ms)
        ).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            RawEvent.event_type == "ZONE_DWELL",
            RawEvent.zone_id != None,
            RawEvent.zone_id != "ENTRY",
            RawEvent.zone_id != "EXIT"
        ).group_by(RawEvent.zone_id).all()

        # Format average dwell as integer milliseconds
        avg_dwell_per_zone = {zone_id: int(avg_dwell) for zone_id, avg_dwell in dwell_results if avg_dwell}
    except Exception as e:
        avg_dwell_per_zone = {}
        logger.error(f"Error calculating average dwells: {str(e)}")

    # 4. Current Queue Depth (from latest event metadata)
    try:
        latest_queue = db.query(RawEvent.queue_depth).filter(
            RawEvent.store_id == id,
            RawEvent.queue_depth != None
        ).order_by(RawEvent.timestamp.desc()).first()
        current_queue_depth = latest_queue[0] if latest_queue else 0
    except Exception as e:
        current_queue_depth = 0
        logger.error(f"Error getting current queue depth: {str(e)}")

    # 5. Abandonment Rate (Ratio of queue joins that abandoned)
    try:
        joins = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            RawEvent.event_type == "BILLING_QUEUE_JOIN"
        ).count()

        abandons = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            RawEvent.event_type == "BILLING_QUEUE_ABANDON"
        ).count()

        abandonment_rate = (abandons / joins) if joins > 0 else 0.0
    except Exception as e:
        abandonment_rate = 0.0
        logger.error(f"Error calculating abandonment rate: {str(e)}")

    return {
        "store_id": id,
        "unique_visitors": unique_visitors_count,
        "conversion_rate": round(conversion_rate, 4),
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "current_queue_depth": current_queue_depth,
        "abandonment_rate": round(abandonment_rate, 4)
    }
