import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("bitget_bot")
DB_FILE = "webhook_logs.db"

def init_db():
    """Initialize SQLite database for storing webhook logs."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                symbol TEXT NOT NULL,
                amount REAL,
                market_type TEXT,
                status TEXT NOT NULL, -- 'success', 'error', 'unauthorized'
                tradingview_payload TEXT,
                exchange_response TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.info("SQLite database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def log_webhook(
    action: str,
    symbol: str,
    amount: float,
    market_type: str,
    status: str,
    tv_payload: Dict[str, Any],
    exchange_response: Dict[str, Any]
) -> int:
    """Log an incoming webhook signal and exchange response."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO webhook_logs 
            (timestamp, action, symbol, amount, market_type, status, tradingview_payload, exchange_response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_str,
            action.upper(),
            symbol.upper(),
            amount,
            market_type,
            status,
            json.dumps(tv_payload, indent=2),
            json.dumps(exchange_response, indent=2)
        ))
        conn.commit()
        log_id = cursor.lastrowid
        conn.close()
        return log_id or 0
    except Exception as e:
        logger.error(f"Error writing log to database: {e}")
        return 0

def get_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve recent webhook logs."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM webhook_logs 
            ORDER BY id DESC 
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        
        logs = []
        for r in rows:
            logs.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "action": r["action"],
                "symbol": r["symbol"],
                "amount": r["amount"],
                "market_type": r["market_type"],
                "status": r["status"],
                "tradingview_payload": json.loads(r["tradingview_payload"] or "{}"),
                "exchange_response": json.loads(r["exchange_response"] or "{}")
            })
        conn.close()
        return logs
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return []

def get_stats() -> Dict[str, Any]:
    """Retrieve aggregate statistics."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM webhook_logs")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM webhook_logs WHERE status = 'success'")
        success = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM webhook_logs WHERE status = 'error'")
        errors = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM webhook_logs WHERE status = 'unauthorized'")
        unauthorized = cursor.fetchone()[0]

        conn.close()
        return {
            "total_signals": total,
            "success_count": success,
            "error_count": errors,
            "unauthorized_count": unauthorized,
            "success_rate": round((success / total * 100), 1) if total > 0 else 100.0
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return {"total_signals": 0, "success_count": 0, "error_count": 0, "unauthorized_count": 0, "success_rate": 100.0}

def clear_logs() -> bool:
    """Clear all webhook logs."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM webhook_logs")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return False

# Initialize on import
init_db()
