from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone
from app.database import get_db
from app.models import RawEvent

router = APIRouter()

@router.get("/health")
def check_health(db: Session = Depends(get_db)):
    health_status = "OK"
    db_status = "connected"
    warnings = []
    last_feed_timestamps = {}
    
    try:
        # Check database connectivity by querying unique store IDs and their max timestamps
        results = db.query(
            RawEvent.store_id, 
            func.max(RawEvent.timestamp)
        ).group_by(RawEvent.store_id).all()
        
        current_time = datetime.now(timezone.utc)
        feed_lag_stale = False
        
        for store_id, max_ts in results:
            if max_ts:
                # Convert SQLite datetime to string and calculate delta
                last_feed_timestamps[store_id] = max_ts.isoformat()
                
                # Check for lag (stale feed warning if lag > 10 minutes)
                # Make max_ts timezone-aware if it isn't
                if max_ts.tzinfo is None:
                    from datetime import timezone as tz
                    max_ts = max_ts.replace(tzinfo=tz.utc)
                time_diff_seconds = (current_time - max_ts).total_seconds()
                if time_diff_seconds > 600: # 10 minutes
                    feed_lag_stale = True
                    warnings.append(
                        f"STALE_FEED: Feed for store {store_id} is stale by {int(time_diff_seconds / 60)} minutes."
                    )
            else:
                last_feed_timestamps[store_id] = None
        
        if feed_lag_stale:
            health_status = "WARN"
            
    except Exception as e:
        health_status = "ERROR"
        db_status = f"disconnected: {str(e)}"
        warnings.append("DATABASE_UNAVAILABLE")

    response_body = {
        "status": health_status,
        "database": db_status,
        "last_event_timestamps": last_feed_timestamps,
        "utc_time": datetime.now(timezone.utc).isoformat()
    }
    
    if warnings:
        response_body["warnings"] = warnings

    # Return HTTP 503 when database is unavailable (graceful degradation)
    if health_status == "ERROR":
        return JSONResponse(status_code=503, content=response_body)
        
    return response_body
