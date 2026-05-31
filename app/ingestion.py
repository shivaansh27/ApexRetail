import os
import logging
from fastapi import APIRouter, Depends, status, HTTPException, Response, Header
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from app.database import get_db
from app.models import RawEvent, EventIngestModel

router = APIRouter()
logger = logging.getLogger("store_intelligence.ingestion")

@router.post("/events/ingest", status_code=status.HTTP_200_OK)
def ingest_events(
    payload: List[Dict[str, Any]], 
    response: Response,
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Ingests batches of up to 500 events.
    Enforces idempotency by event_id.
    Implements partial success on malformed events.
    Returns HTTP 400 Bad Request for completely malformed batches or size limit breaches.
    """
    # Optional API Key Authentication
    INGESTION_API_KEY = os.environ.get("INGESTION_API_KEY")
    if INGESTION_API_KEY:
        if not x_api_key or x_api_key != INGESTION_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key."
            )

    if not isinstance(payload, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must be a JSON array of events."
        )

    if len(payload) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds the limit of 500. Received: {len(payload)}"
        )

    if len(payload) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty ingestion payload. Batch must contain at least 1 event."
        )

    inserted_count = 0
    skipped_count = 0
    errors = []
    
    # 1. First Pass: Validate structures using Pydantic and accumulate valid objects
    valid_pydantic_events: List[EventIngestModel] = []
    
    for idx, item in enumerate(payload):
        try:
            # Manually parse using Pydantic to support partial success
            validated_event = EventIngestModel.model_validate(item)
            valid_pydantic_events.append(validated_event)
        except Exception as err:
            logger.warning(f"Validation failure at index {idx} (ID: {item.get('event_id', 'unknown')}): {str(err)}")
            errors.append({
                "index": idx,
                "event_id": item.get("event_id", "unknown"),
                "error_type": "VALIDATION_ERROR",
                "detail": str(err)
            })

    # If the entire batch was structured but completely failed validation, return HTTP 400
    if len(errors) == len(payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "All events in the batch failed structural validation.",
                "errors": errors
            }
        )

    # 2. Bulk-check existing database records for Idempotency
    batch_ids = [evt.event_id for evt in valid_pydantic_events]
    
    try:
        existing_records = db.query(RawEvent.event_id).filter(RawEvent.event_id.in_(batch_ids)).all()
        existing_ids = {r[0] for r in existing_records}
    except Exception as e:
        logger.error(f"Database lookup error during idempotency check: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during idempotency check: {str(e)}"
        )

    new_events = []
    seen_in_batch = set() # Avoid inserting duplicates present within the SAME batch
    
    for evt in valid_pydantic_events:
        if evt.event_id in existing_ids:
            skipped_count += 1
            continue
            
        if evt.event_id in seen_in_batch:
            skipped_count += 1
            continue
            
        seen_in_batch.add(evt.event_id)
        
        # Flatten Pydantic model for SQLAlchemy ORM
        raw_db_event = RawEvent(
            event_id=evt.event_id,
            store_id=evt.store_id.strip(),
            camera_id=evt.camera_id.strip(),
            visitor_id=evt.visitor_id.strip(),
            event_type=evt.event_type.strip(),
            timestamp=evt.timestamp,
            zone_id=evt.zone_id.strip() if evt.zone_id else None,
            dwell_ms=evt.dwell_ms,
            is_staff=evt.is_staff,
            confidence=evt.confidence,
            # Metadata fields (nested -> flat mapping)
            queue_depth=evt.metadata.queue_depth,
            sku_zone=evt.metadata.sku_zone.strip() if evt.metadata.sku_zone else None,
            session_seq=evt.metadata.session_seq
        )
        new_events.append(raw_db_event)

    # 3. Perform Bulk Ingestion
    if new_events:
        try:
            db.bulk_save_objects(new_events)
            db.commit()
            inserted_count = len(new_events)
            logger.info(f"Ingested batch: {inserted_count} inserted, {skipped_count} skipped, {len(errors)} errors.")
        except Exception as e:
            db.rollback()
            logger.error(f"Database error during bulk write: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database write error: {str(e)}"
            )
    else:
        logger.info(f"Ingested batch: 0 inserted, {skipped_count} skipped (all duplicates), {len(errors)} errors.")

    # Expose ingested event count to custom header for middleware logging
    response.headers["X-Ingested-Events"] = str(inserted_count)

    return {
        "success": len(errors) == 0 or inserted_count > 0,
        "inserted": inserted_count,
        "skipped": skipped_count,
        "errors": errors
    }
