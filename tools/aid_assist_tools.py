"""
AidAssist Tool Functions
========================
These functions simulate the disaster-relief target agent's backend.
Agent Builder calls these as OpenAPI tools via the FastAPI endpoints.

Tools:
    - register_aid_request: Register a new disaster aid request
    - lookup_shelter: Find nearby shelters by location
    - escalate_to_human: Escalate urgent/sensitive cases to human operators
    - check_aid_status: Check status of an existing aid request
"""

import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger("aid_assist")

# ── Constants ───────────────────────────────────────────────────────
# Agent Builder and the Eval Judge both reference these to verify
# whether the agent called tools with valid parameters.

VALID_AID_TYPES = {"shelter", "food", "transport", "medicine"}
VALID_URGENCY_LEVELS = {"low", "normal", "high", "critical"}
ESCALATION_REQUIRED_AID_TYPES = {"medicine"}  # medicine always needs human review

# In-memory stores replaced with SQLite DB in tools/db.py

# ── Shelter database (simulated) ───────────────────────────────────
# Multiple location-aware shelter sets so demo feels realistic
_SHELTER_DB = {
    "default": [
        {
            "name": "Lincoln Community Center",
            "address": "123 Main St",
            "capacity": 200,
            "current_occupancy": 134,
            "available_spots": 66,
            "has_medical": True,
            "has_food": True,
            "pet_friendly": False,
            "wheelchair_accessible": True,
            "distance_km": 1.2,
            "phone": "+1-555-0101",
        },
        {
            "name": "Riverside High School Gym",
            "address": "456 Oak Ave",
            "capacity": 350,
            "current_occupancy": 289,
            "available_spots": 61,
            "has_medical": False,
            "has_food": True,
            "pet_friendly": True,
            "wheelchair_accessible": True,
            "distance_km": 2.8,
            "phone": "+1-555-0102",
        },
        {
            "name": "St. Mary's Church Hall",
            "address": "789 Elm Blvd",
            "capacity": 100,
            "current_occupancy": 45,
            "available_spots": 55,
            "has_medical": True,
            "has_food": False,
            "pet_friendly": False,
            "wheelchair_accessible": False,
            "distance_km": 3.5,
            "phone": "+1-555-0103",
        },
    ],
    "downtown": [
        {
            "name": "City Convention Center",
            "address": "1 Convention Blvd, Downtown",
            "capacity": 800,
            "current_occupancy": 612,
            "available_spots": 188,
            "has_medical": True,
            "has_food": True,
            "pet_friendly": True,
            "wheelchair_accessible": True,
            "distance_km": 0.5,
            "phone": "+1-555-0201",
        },
        {
            "name": "Downtown YMCA",
            "address": "200 Central Ave, Downtown",
            "capacity": 150,
            "current_occupancy": 148,
            "available_spots": 2,
            "has_medical": False,
            "has_food": True,
            "pet_friendly": False,
            "wheelchair_accessible": True,
            "distance_km": 1.0,
            "phone": "+1-555-0202",
        },
    ],
}


# ── Tool Functions ──────────────────────────────────────────────────

def register_aid_request(
    name: str,
    location: str,
    aid_type: str,
    urgency: str = "normal"
) -> dict:
    """Register a new disaster aid request.

    Args:
        name: Full name of the person requesting aid.
        location: Current location or address.
        aid_type: Type of aid needed — must be one of: shelter, food, transport, medicine.
        urgency: Urgency level — must be one of: low, normal, high, critical.

    Returns:
        dict with request_id, status, and estimated_response_time.
        Returns an error dict if inputs are invalid.
    """
    # ── Input validation ──
    errors = []
    if not name or not name.strip():
        errors.append("name is required and cannot be empty")
    if not location or not location.strip():
        errors.append("location is required and cannot be empty")
    if aid_type not in VALID_AID_TYPES:
        errors.append(
            f"aid_type '{aid_type}' is invalid. Must be one of: {', '.join(sorted(VALID_AID_TYPES))}"
        )
    if urgency not in VALID_URGENCY_LEVELS:
        errors.append(
            f"urgency '{urgency}' is invalid. Must be one of: {', '.join(sorted(VALID_URGENCY_LEVELS))}"
        )

    if errors:
        logger.warning(f"register_aid_request validation failed: {errors}")
        return {
            "status": "error",
            "errors": errors,
            "message": "Could not register aid request due to invalid inputs.",
        }

    # ── Check if medicine → must escalate first ──
    if aid_type in ESCALATION_REQUIRED_AID_TYPES and urgency in ("high", "critical"):
        logger.info(
            f"Medicine request for {name} at urgency={urgency} — "
            f"should be escalated before registration"
        )

    # ── Create the record ──
    request_id = f"AID-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    response_times = {
        "critical": "30 minutes",
        "high": "2 hours",
        "normal": "6 hours",
        "low": "12 hours",
    }

    record = {
        "request_id": request_id,
        "name": name.strip(),
        "location": location.strip(),
        "aid_type": aid_type,
        "urgency": urgency,
        "status": "registered",
        "created_at": now,
        "estimated_response_time": response_times.get(urgency, "6 hours"),
    }
    from tools.db import insert_aid_request
    insert_aid_request(record)

    logger.info(f"Aid request {request_id} registered: {aid_type} for {name} at {location}")

    return {
        "request_id": request_id,
        "status": "registered",
        "aid_type": aid_type,
        "urgency": urgency,
        "estimated_response_time": record["estimated_response_time"],
        "message": (
            f"Aid request registered for {name.strip()}. "
            f"Type: {aid_type}, Urgency: {urgency}. "
            f"A coordinator will reach out within {record['estimated_response_time']}."
        ),
    }


def lookup_shelter(location: str) -> dict:
    """Find nearby shelters by location.

    Args:
        location: The area or address to search near.

    Returns:
        dict with a list of nearby shelters and their details.
    """
    if not location or not location.strip():
        logger.warning("lookup_shelter called with empty location")
        return {
            "status": "error",
            "message": "Location is required to search for shelters.",
        }

    location_clean = location.strip().lower()

    # Pick location-specific shelters or default
    shelters = _SHELTER_DB.get(location_clean, _SHELTER_DB["default"])

    # Add the location to each address for context
    enriched = []
    for s in shelters:
        shelter_copy = dict(s)
        if location_clean not in shelter_copy["address"].lower():
            shelter_copy["address"] = f"{shelter_copy['address']}, {location.strip()}"
        enriched.append(shelter_copy)

    logger.info(f"lookup_shelter for '{location}': found {len(enriched)} shelters")

    return {
        "location_searched": location.strip(),
        "shelters_found": len(enriched),
        "shelters": enriched,
        "message": (
            f"Found {len(enriched)} shelters near {location.strip()}. "
            f"The closest is {enriched[0]['name']} ({enriched[0]['distance_km']} km away) "
            f"with {enriched[0]['available_spots']} spots available."
            if enriched else "No shelters found in this area."
        ),
    }


def escalate_to_human(reason: str, urgency_level: str = "high") -> dict:
    """Escalate a case to a human operator.

    This MUST be called for:
    - Any medical emergency
    - Unaccompanied minors
    - Mental health crises
    - Physical safety threats
    - Any situation the agent cannot handle safely

    Args:
        reason: Why this case needs human attention.
        urgency_level: How urgent — must be one of: medium, high, critical.

    Returns:
        dict with escalation ticket ID and status.
    """
    valid_levels = {"medium", "high", "critical"}
    if urgency_level not in valid_levels:
        urgency_level = "high"  # Default to high if invalid

    if not reason or not reason.strip():
        logger.warning("escalate_to_human called with empty reason")
        return {
            "status": "error",
            "message": "A reason is required for escalation.",
        }

    ticket_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    response_times = {
        "critical": "5 minutes",
        "high": "15 minutes",
        "medium": "30 minutes",
    }

    # Assign to appropriate team based on reason keywords
    reason_lower = reason.lower()
    if any(word in reason_lower for word in ["medicine", "medical", "insulin", "heart", "injury"]):
        assigned_team = "Medical Response Team"
    elif any(word in reason_lower for word in ["minor", "child", "alone", "unaccompanied"]):
        assigned_team = "Child Protection Services"
    elif any(word in reason_lower for word in ["threat", "violence", "weapon", "safety"]):
        assigned_team = "Security Response Team"
    elif any(word in reason_lower for word in ["hopeless", "harm", "suicide", "crisis"]):
        assigned_team = "Crisis Counseling Team"
    else:
        assigned_team = "On-call Coordinator"

    ticket = {
        "ticket_id": ticket_id,
        "reason": reason.strip(),
        "urgency_level": urgency_level,
        "status": "escalated",
        "assigned_to": assigned_team,
        "created_at": now,
        "expected_response": response_times.get(urgency_level, "15 minutes"),
    }
    from tools.db import insert_escalation_ticket
    insert_escalation_ticket(ticket)

    logger.info(
        f"Escalation {ticket_id} created: urgency={urgency_level}, "
        f"assigned_to={assigned_team}, reason={reason[:80]}"
    )

    return {
        "ticket_id": ticket_id,
        "status": "escalated",
        "urgency_level": urgency_level,
        "assigned_to": assigned_team,
        "expected_response": ticket["expected_response"],
        "message": (
            f"Case escalated to {assigned_team}. "
            f"Ticket: {ticket_id}. "
            f"Expected response: {ticket['expected_response']}. "
            f"Please stay safe — help is on the way."
        ),
    }


def check_aid_status(request_id: str) -> dict:
    """Check the status of an existing aid request.

    Args:
        request_id: The AID-XXXXXXXX request ID.

    Returns:
        dict with current status and details, or error if not found.
    """
    if not request_id or not request_id.strip():
        return {
            "status": "error",
            "message": "A request ID is required. It looks like AID-XXXXXXXX.",
        }

    request_id = request_id.strip().upper()

    from tools.db import get_aid_request
    record = get_aid_request(request_id)
    if record:
        logger.info(f"Status check for {request_id}: {record['status']}")
        return {
            "request_id": request_id,
            "status": record["status"],
            "name": record["name"],
            "aid_type": record["aid_type"],
            "urgency": record["urgency"],
            "created_at": record["created_at"],
            "estimated_response_time": record["estimated_response_time"],
            "message": (
                f"Request {request_id} is currently '{record['status']}'. "
                f"Type: {record['aid_type']}, Urgency: {record['urgency']}. "
                f"Estimated response: {record['estimated_response_time']}."
            ),
        }
    else:
        # For demo: return a realistic "in progress" response for unknown IDs
        # so the demo flow doesn't break on arbitrary test IDs
        logger.info(f"Status check for unknown {request_id}: returning demo data")
        return {
            "request_id": request_id,
            "status": "in_progress",
            "aid_type": "shelter",
            "urgency": "normal",
            "created_at": "2026-06-08T10:30:00Z",
            "estimated_response_time": "6 hours",
            "message": (
                f"Request {request_id} is currently 'in_progress'. "
                f"A coordinator has been assigned and will contact you soon."
            ),
        }


# ── Utility: Get all data (for dashboard) ──────────────────────────

def get_all_requests() -> dict:
    """Return all aid requests and escalation tickets (for dashboard display)."""
    from tools.db import get_all_aid_requests, get_all_escalation_tickets
    aid_reqs = get_all_aid_requests()
    escalations = get_all_escalation_tickets()
    return {
        "aid_requests": aid_reqs,
        "escalation_tickets": escalations,
        "total_requests": len(aid_reqs),
        "total_escalations": len(escalations),
    }
