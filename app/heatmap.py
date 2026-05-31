from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import RawEvent

router = APIRouter()

@router.get("/stores/{id}/heatmap")
def get_store_heatmap(
    id: str = Path(..., description="Store ID, e.g. ST1008"),
    db: Session = Depends(get_db)
):
    """
    Returns zone-wise visit frequency and average dwell times, 
    normalized to a 0–100 scale, and maps it directly to visual zones.
    """
    try:
        # 1. Check Data Confidence: Count unique sessions in active data
        unique_sessions_count = db.query(RawEvent.visitor_id).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False
        ).distinct().count()
        
        data_confidence = unique_sessions_count >= 20

        # 2. Query total footfalls (frequencies) per zone
        # We count all ZONE_ENTER events per zone
        frequency_query = db.query(
            RawEvent.zone_id,
            func.count(RawEvent.event_id)
        ).filter(
            RawEvent.store_id == id,
            RawEvent.is_staff == False,
            (RawEvent.event_type == "ZONE_ENTER") | (RawEvent.event_type == "BILLING_QUEUE_JOIN"),
            RawEvent.zone_id != None,
            RawEvent.zone_id != "ENTRY",
            RawEvent.zone_id != "EXIT"
        ).group_by(RawEvent.zone_id).all()

        frequencies = {zone: count for zone, count in frequency_query if zone}

        # 3. Query average dwell times per zone
        dwell_query = db.query(
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

        dwells = {zone: int(avg_dwell) for zone, avg_dwell in dwell_query if zone and avg_dwell}

        # 4. Normalize Frequencies (0-100)
        max_frequency = max(frequencies.values()) if frequencies else 0
        max_dwell = max(dwells.values()) if dwells else 0

        heatmap_data = {}
        # Union of all zones in frequencies and dwells
        all_zones = set(frequencies.keys()) | set(dwells.keys())

        for zone in all_zones:
            freq = frequencies.get(zone, 0)
            dw = dwells.get(zone, 0)

            normalized_freq = round((freq / max_frequency) * 100, 2) if max_frequency > 0 else 0.0
            normalized_dwell = round((dw / max_dwell) * 100, 2) if max_dwell > 0 else 0.0

            heatmap_data[zone] = {
                "raw_frequency": freq,
                "raw_avg_dwell_ms": dw,
                "normalized_frequency": normalized_freq,
                "normalized_dwell": normalized_dwell,
                # Composite index for heat intensity
                "intensity_score": round((normalized_freq * 0.6) + (normalized_dwell * 0.4), 2)
            }

        return {
            "store_id": id,
            "data_confidence": data_confidence,
            "unique_sessions_in_window": unique_sessions_count,
            "zones": heatmap_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error on heatmap generation: {str(e)}")
