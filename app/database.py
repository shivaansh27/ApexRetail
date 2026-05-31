import os
import csv
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base, POSTransaction

# Setup logger for database module
logger = logging.getLogger("store_intelligence.database")

# Portability & CI/CD compliance: Read DB path from environment variable, fallback to relative store_intelligence.db
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DB_PATH = os.environ.get("DB_PATH", "store_intelligence.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"

logger.info(f"Connecting to database: {DATABASE_URL}")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} # Required for SQLite multi-threading
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    # 1. Create tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized successfully.")
    
    # 2. Seed POS Transactions from CSV if empty
    db = SessionLocal()
    try:
        count = db.query(POSTransaction).count()
        if count == 0:
            logger.info("POS Transaction database is empty. Seeding from CSV...")
            
            # Search for POS CSV in various relative and absolute paths
            csv_candidates = [
                "Brigade_Bangalore_10_April_26 (1)bc6219c.csv",
                "pos_transactions.csv",
                os.path.join(os.getcwd(), "Brigade_Bangalore_10_April_26 (1)bc6219c.csv"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Brigade_Bangalore_10_April_26 (1)bc6219c.csv")
            ]
            
            csv_path = None
            for candidate in csv_candidates:
                if os.path.exists(candidate):
                    csv_path = candidate
                    break
                    
            if csv_path:
                logger.info(f"Found CSV for seeding: {csv_path}")
                transactions_to_seed = []
                unique_txns = set()
                
                with open(csv_path, mode="r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        txn_id = row.get("invoice_number") or row.get("order_id")
                        if not txn_id or txn_id in unique_txns:
                            continue
                        
                        unique_txns.add(txn_id)
                        
                        order_date = row.get("order_date", "10-04-2026")
                        order_time = row.get("order_time", "00:00:00")
                        try:
                            dt_str = f"{order_date.strip()} {order_time.strip()}"
                            timestamp = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
                        except Exception:
                            timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
                        
                        try:
                            basket_val = float(row.get("total_amount") or row.get("NMV") or 0.0)
                            qty = int(row.get("qty") or 1)
                        except Exception:
                            basket_val = 0.0
                            qty = 1
                            
                        txn = POSTransaction(
                            transaction_id=txn_id,
                            store_id=row.get("store_id", "ST1008").strip(),
                            timestamp=timestamp,
                            basket_value_inr=basket_val,
                            qty=qty,
                            customer_name=row.get("customer_name", "Guest").strip()
                        )
                        transactions_to_seed.append(txn)
                
                if transactions_to_seed:
                    db.bulk_save_objects(transactions_to_seed)
                    db.commit()
                    logger.info(f"Successfully seeded {len(transactions_to_seed)} transactions from CSV.")
            else:
                logger.warning("Could not find any transaction CSV file. Seeding transactions matching events.jsonl...")
                # Dynamically extract and seed transactions matching the checked-in events.jsonl
                events_candidates = [
                    "events.jsonl",
                    os.path.join(os.getcwd(), "events.jsonl"),
                    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "events.jsonl")
                ]
                
                events_path = None
                for candidate in events_candidates:
                    if os.path.exists(candidate):
                        events_path = candidate
                        break
                
                seeded_txns = []
                if events_path:
                    logger.info(f"Extracting transactions from: {events_path}")
                    try:
                        import json
                        seen_visitors = set()
                        with open(events_path, "r", encoding="utf-8") as f:
                            for line in f:
                                if not line.strip():
                                    continue
                                evt = json.loads(line)
                                vis_id = evt.get("visitor_id", "")
                                if vis_id.startswith("VIS_C_") and evt.get("event_type") == "ZONE_DWELL" and evt.get("zone_id") == "CASH_COUNTER":
                                    if vis_id not in seen_visitors:
                                        seen_visitors.add(vis_id)
                                        ts_str = evt["timestamp"]
                                        if ts_str.endswith("Z"):
                                            ts_str = ts_str[:-1]
                                        timestamp = datetime.fromisoformat(ts_str)
                                        
                                        # Calculate a realistic mock amount and quantity based on visitor id suffix
                                        suffix = vis_id.split('_')[-1]
                                        num_idx = int(suffix) if suffix.isdigit() else 0
                                        basket_val = float(100.0 * (num_idx % 10 + 5))
                                        qty = (num_idx % 3 + 1)
                                        
                                        seeded_txns.append(
                                            POSTransaction(
                                                transaction_id=f"TXN_{vis_id}",
                                                store_id=evt.get("store_id", "ST1008").strip(),
                                                timestamp=timestamp,
                                                basket_value_inr=basket_val,
                                                qty=qty,
                                                customer_name="Guest"
                                            )
                                        )
                    except Exception as parse_err:
                        logger.error(f"Failed to parse events.jsonl for seeding: {str(parse_err)}")
                        
                if seeded_txns:
                    db.bulk_save_objects(seeded_txns)
                    db.commit()
                    logger.info(f"Successfully seeded {len(seeded_txns)} transactions matched from events.jsonl.")
                else:
                    logger.warning("Could not extract events from events.jsonl. Seeding absolute fallbacks...")
                    # Ultimate fallback mock transactions matching original mock events with CORRECT aligned times
                    fallback_txns = [
                        POSTransaction(
                            transaction_id="TXN_MOCK_001",
                            store_id="ST1008",
                            timestamp=datetime(2026, 4, 10, 12, 15, 0),
                            basket_value_inr=500.0,
                            qty=1,
                            customer_name="Guest"
                        ),
                        POSTransaction(
                            transaction_id="TXN_MOCK_002",
                            store_id="ST1008",
                            timestamp=datetime(2026, 4, 10, 12, 45, 0),
                            basket_value_inr=1200.0,
                            qty=2,
                            customer_name="Nivya"
                        ),
                        POSTransaction(
                            transaction_id="TXN_MOCK_003",
                            store_id="ST1008",
                            timestamp=datetime(2026, 4, 10, 13, 30, 0),
                            basket_value_inr=800.0,
                            qty=1,
                            customer_name="Guest"
                        )
                    ]
                    db.bulk_save_objects(fallback_txns)
                    db.commit()
                    logger.info(f"Successfully seeded {len(fallback_txns)} fallback mock transactions.")
        else:
            logger.info(f"POS Transaction database already has {count} records. Seeding skipped.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error during database initialization/seeding: {str(e)}")
    finally:
        db.close()
