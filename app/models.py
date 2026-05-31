from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Index
from sqlalchemy.orm import declarative_base

# ==========================================
# SQLAlchemy ORM Database Schemas
# ==========================================
Base = declarative_base()

class RawEvent(Base):
    __tablename__ = "raw_events"

    event_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, nullable=False)
    camera_id = Column(String, nullable=False)
    visitor_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer, nullable=False, default=0)
    is_staff = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=False, default=1.0)
    
    # Metadata fields (flattened in DB for easy querying)
    queue_depth = Column(Integer, nullable=True)
    sku_zone = Column(String, nullable=True)
    session_seq = Column(Integer, nullable=False, default=1)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Database Indexes for High-Performance Queries
    __table_args__ = (
        Index("idx_events_store_time", "store_id", "timestamp"),
        Index("idx_events_visitor", "visitor_id"),
        Index("idx_events_type", "event_type"),
    )

class POSTransaction(Base):
    __tablename__ = "pos_transactions"

    transaction_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    basket_value_inr = Column(Float, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    customer_name = Column(String, nullable=True)

# ==========================================
# Pydantic Schemas for API Requests & Validation
# ==========================================
class EventMetadata(BaseModel):
    queue_depth: Optional[int] = Field(None, description="Queue depth for BILLING_QUEUE_JOIN")
    sku_zone: Optional[str] = Field(None, description="Product / Brand zone sub-label")
    session_seq: int = Field(1, description="Ordinal position of this event in the visitor session")

class EventIngestModel(BaseModel):
    event_id: str = Field(..., description="UUIDv4 globally unique identifier")
    store_id: str = Field(..., description="Store ID, e.g. ST1008")
    camera_id: str = Field(..., description="Camera identifier, e.g. CAM_ENTRY_01")
    visitor_id: str = Field(..., description="Persistent tracking token per session")
    event_type: str = Field(..., description="ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL, BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY")
    timestamp: datetime = Field(..., description="ISO-8601 UTC timestamp")
    zone_id: Optional[str] = Field(None, description="Brand zone ID, null for ENTRY/EXIT")
    dwell_ms: int = Field(0, description="Dwell duration in milliseconds")
    is_staff: bool = Field(False, description="Staff filtering flag")
    confidence: float = Field(1.0, description="Confidence of detection between 0 and 1")
    metadata: EventMetadata = Field(default_factory=EventMetadata, description="Event nested metadata")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        valid_types = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
        }
        if v not in valid_types:
            raise ValueError(f"Invalid event_type: {v}. Must be one of {valid_types}")
        return v
