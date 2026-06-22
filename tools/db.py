"""
SQLite Database Utility
=======================
Handles data persistence for aid requests, escalation tickets, and human approvals.
Replaces temporary in-memory dictionaries so data is not lost on FastAPI reload or Cloud Run scale down.
"""

import os
import sqlite3
import json
import logging
import threading

logger = logging.getLogger("db")

# Place database file in the project root directory
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "red_team.db"))

_local = threading.local()


def get_connection():
    """Return a thread-local SQLite connection (reused per worker thread)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def init_db():
    """Initialize database tables if they do not exist."""
    logger.info(f"Initializing SQLite database at: {DB_PATH}")
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Aid Requests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS aid_requests (
            request_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            aid_type TEXT NOT NULL,
            urgency TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            estimated_response_time TEXT NOT NULL
        )
    """)

    # 2. Escalation Tickets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS escalation_tickets (
            ticket_id TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            urgency_level TEXT NOT NULL,
            status TEXT NOT NULL,
            assigned_to TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expected_response TEXT NOT NULL
        )
    """)

    # 3. Human Approval Requests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            risk TEXT NOT NULL,
            proposed_change TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            approved_at TEXT
        )
    """)

    # 4. Test Evaluations table (for live dashboard results)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            scenario_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            safety TEXT NOT NULL,
            privacy TEXT NOT NULL,
            escalation TEXT NOT NULL,
            tool_use TEXT NOT NULL,
            groundedness TEXT NOT NULL,
            overall TEXT NOT NULL,
            reason TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            trace_id TEXT,
            user_message TEXT,
            expected_behavior TEXT
        )
    """)

    # Attempt migration if table was already created without trace_id or new columns
    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN trace_id TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN user_message TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE evaluations ADD COLUMN expected_behavior TEXT")
    except sqlite3.OperationalError:
        pass

    # Enable WAL mode for concurrent read/write safety
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception as e:
        logger.warning(f"Could not enable WAL mode: {e}")

    # Performance indexes for dashboard queries
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluations_timestamp ON evaluations(timestamp DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluations_category ON evaluations(category)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status)"
    )

    conn.commit()
    # Thread-local connection — do not close per operation
    logger.info("Database tables initialized successfully.")


# ── Aid Request Helpers ──────────────────────────────────────────────

def insert_aid_request(record: dict) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO aid_requests 
        (request_id, name, location, aid_type, urgency, status, created_at, estimated_response_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["request_id"],
            record["name"],
            record["location"],
            record["aid_type"],
            record["urgency"],
            record["status"],
            record["created_at"],
            record["estimated_response_time"],
        ),
    )
    conn.commit()
    # Thread-local connection — do not close per operation


def get_aid_request(request_id: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aid_requests WHERE request_id = ?", (request_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None


def get_all_aid_requests() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aid_requests ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


# ── Escalation Ticket Helpers ────────────────────────────────────────

def insert_escalation_ticket(ticket: dict) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO escalation_tickets 
        (ticket_id, reason, urgency_level, status, assigned_to, created_at, expected_response)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket["ticket_id"],
            ticket["reason"],
            ticket["urgency_level"],
            ticket["status"],
            ticket["assigned_to"],
            ticket["created_at"],
            ticket["expected_response"],
        ),
    )
    conn.commit()
    # Thread-local connection — do not close per operation


def get_all_escalation_tickets() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM escalation_tickets ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


# ── Approval Gate Helpers ────────────────────────────────────────────

def insert_approval_request(req: dict) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO approvals 
        (approval_id, action, reason, risk, proposed_change, status, created_at, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            req["approval_id"],
            req["action"],
            req["reason"],
            req["risk"],
            req["proposed_change"],
            req["status"],
            req["created_at"],
            req.get("approved_at"),
        ),
    )
    conn.commit()
    # Thread-local connection — do not close per operation


def get_approval_request(approval_id: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None


def get_pending_approvals() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_approvals() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals ORDER BY created_at DESC")
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def update_approval_status(approval_id: str, status: str, approved_at: str = None) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE approvals 
        SET status = ?, approved_at = ?
        WHERE approval_id = ?
        """,
        (status, approved_at, approval_id),
    )
    rowcount = cursor.rowcount
    conn.commit()
    # Thread-local connection — do not close per operation
    return rowcount > 0


# ── Test Evaluation Helpers ──────────────────────────────────────────

def insert_evaluation(record: dict) -> None:
    """Insert or replace a test scenario evaluation result."""
    from datetime import datetime, timezone
    conn = get_connection()
    cursor = conn.cursor()
    
    timestamp = record.get("timestamp") or datetime.now(timezone.utc).isoformat()
    scores = record.get("scores", {})
    
    cursor.execute(
        """
        INSERT OR REPLACE INTO evaluations 
        (scenario_id, category, safety, privacy, escalation, tool_use, groundedness, overall, reason, timestamp, trace_id, user_message, expected_behavior)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["scenario_id"],
            record.get("category", "unknown"),
            scores.get("safety", "n/a"),
            scores.get("privacy", "n/a"),
            scores.get("escalation", "n/a"),
            scores.get("tool_use", "n/a"),
            scores.get("groundedness", "n/a"),
            record.get("overall", "fail"),
            record.get("reason", ""),
            timestamp,
            record.get("trace_id"),
            record.get("user_message", ""),
            record.get("expected_behavior", "")
        ),
    )
    conn.commit()
    # Thread-local connection — do not close per operation


def get_all_evaluations() -> list[dict]:
    """Retrieve all stored evaluation results, ordered by category and scenario."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM evaluations ORDER BY timestamp DESC, scenario_id ASC")
    rows = cursor.fetchall()
    # Thread-local connection — do not close per operation
    
    # Format database rows back into nested dictionary structure expected by eval utilities
    results = []
    for row in rows:
        d = dict(row)
        results.append({
            "scenario_id": d["scenario_id"],
            "category": d["category"],
            "scores": {
                "safety": d["safety"],
                "privacy": d["privacy"],
                "escalation": d["escalation"],
                "tool_use": d["tool_use"],
                "groundedness": d["groundedness"]
            },
            "overall": d["overall"],
            "reason": d["reason"],
            "timestamp": d["timestamp"],
            "trace_id": d.get("trace_id"),
            "user_message": d.get("user_message", ""),
            "expected_behavior": d.get("expected_behavior", "")
        })
    return results


def reset_db() -> None:
    """Clear all data from all database tables to reset the dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM evaluations")
    cursor.execute("DELETE FROM approvals")
    cursor.execute("DELETE FROM escalation_tickets")
    cursor.execute("DELETE FROM aid_requests")
    conn.commit()
    # Thread-local connection — do not close per operation
    logger.info("Database reset: cleared all tables.")


# Auto-initialize database when the module is imported (or on first use)
try:
    init_db()
except Exception as e:
    logger.error(f"Failed to auto-initialize SQLite database: {e}")

