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

logger = logging.getLogger("db")

# Place database file in the project root directory
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "red_team.db"))


def get_connection():
    """Return a thread-safe connection to the SQLite database.
    Since SQLite uses file locks, we open a new connection for each request/transaction."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
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

    conn.commit()
    conn.close()
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
    conn.close()


def get_aid_request(request_id: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aid_requests WHERE request_id = ?", (request_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_all_aid_requests() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM aid_requests ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
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
    conn.close()


def get_all_escalation_tickets() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM escalation_tickets ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
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
    conn.close()


def get_approval_request(approval_id: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_pending_approvals() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_approvals() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM approvals ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
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
    conn.close()
    return rowcount > 0


# Auto-initialize database when the module is imported (or on first use)
try:
    init_db()
except Exception as e:
    logger.error(f"Failed to auto-initialize SQLite database: {e}")
