import os
import time
import uuid
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.health import router as health_router
from app.ingestion import router as ingestion_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.anomalies import router as anomalies_router

# Configure structured console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("store_intelligence.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Purplle Store Intelligence API database schema...")
    init_db()
    yield

app = FastAPI(
    title="Purplle Store Intelligence API",
    description="Containerized API for real-time store footfall and purchase conversion analytics",
    version="1.0.0",
    lifespan=lifespan
)

# Tighten CORS openness for production readiness
# Allow configuring specific domains in production, falling back to wildcard in development
cors_origins_str = os.environ.get("CORS_ORIGINS", "*")
if cors_origins_str == "*":
    allow_origins = ["*"]
else:
    allow_origins = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Structured Logging Middleware (Part C compliant)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())
    start_time = time.time()
    
    # Process the request
    response = await call_next(request)
    
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Extract store_id if present in path parameters
    path_params = request.path_params
    store_id = path_params.get("id") or "N/A"
    
    # Calculate event count if parsing ingestion payload
    event_count = "N/A"
    if request.url.path == "/events/ingest" and request.method == "POST":
        # Event count is mapped in response headers or response body by ingestion handler
        event_count = response.headers.get("X-Ingested-Events", "N/A")

    # Structured, searchable log output (Part C requirement)
    logger.info(
        f"trace_id={trace_id} store_id={store_id} endpoint={request.url.path} "
        f"latency_ms={latency_ms} event_count={event_count} status_code={response.status_code}"
    )
    
    response.headers["X-Trace-ID"] = trace_id
    return response

# Routers register below

# Register Routers
app.include_router(health_router, tags=["Health"])
app.include_router(ingestion_router, tags=["Ingestion"])
app.include_router(metrics_router, tags=["Analytics"])
app.include_router(funnel_router, tags=["Analytics"])
app.include_router(heatmap_router, tags=["Analytics"])
app.include_router(anomalies_router, tags=["Analytics"])
