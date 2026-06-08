"""
Human Approval Gate Functions
=============================
Functions for the human-in-the-loop approval workflow.
No automated changes are applied to the target agent without human approval.

Tools:
    - request_human_approval: Create an approval request for a proposed change
    - apply_approved_improvement: Apply a human-approved prompt/tool patch
"""

import uuid
from datetime import datetime


# In-memory approval queue replaced with SQLite DB in tools/db.py


def request_human_approval(
    action: str,
    reason: str,
    risk: str = "medium",
    proposed_change: str = ""
) -> dict:
    """Create an approval request for a proposed improvement.

    Args:
        action: What change is being proposed (e.g., 'update_system_prompt').
        reason: Why this change is needed (linked to failure evidence).
        risk: Risk level of the change (low, medium, high).
        proposed_change: The actual content of the proposed change.

    Returns:
        dict with approval request ID and status.
    """
    approval_id = f"APR-{uuid.uuid4().hex[:8].upper()}"
    request = {
        "approval_id": approval_id,
        "action": action,
        "reason": reason,
        "risk": risk,
        "proposed_change": proposed_change,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    from tools.db import insert_approval_request
    insert_approval_request(request)
    return {
        "approval_id": approval_id,
        "status": "pending",
        "message": f"Approval request created. A human must review and approve "
                   f"before the change is applied. Risk level: {risk}.",
    }


def apply_approved_improvement(approval_id: str, prompt_patch: str = "") -> dict:
    """Apply a human-approved improvement to the target agent.

    Args:
        approval_id: The APR-XXXXXXXX approval ID.
        prompt_patch: The new prompt content to apply (if applicable).

    Returns:
        dict with confirmation that the improvement was applied.
    """
    from tools.db import get_approval_request, update_approval_status
    record = get_approval_request(approval_id)
    if record:
        if record["status"] != "approved":
            return {
                "approval_id": approval_id,
                "status": "rejected",
                "message": "Cannot apply — this change has not been approved by a human yet.",
            }
        update_approval_status(approval_id, "applied")
        return {
            "approval_id": approval_id,
            "status": "applied",
            "message": "Improvement applied successfully. Re-run tests to verify.",
        }
    else:
        return {
            "approval_id": approval_id,
            "status": "not_found",
            "message": "Approval request not found.",
        }


def get_pending_approvals() -> dict:
    """Get all pending approval requests.

    Returns:
        dict with list of pending approval requests.
    """
    from tools.db import get_pending_approvals as db_get_pending
    pending = db_get_pending()
    return {
        "pending_count": len(pending),
        "approvals": pending,
    }


def approve_request(approval_id: str) -> dict:
    """Approve a pending request (called from dashboard UI).

    Args:
        approval_id: The APR-XXXXXXXX approval ID to approve.

    Returns:
        dict with updated status.
    """
    from tools.db import update_approval_status
    approved_at = datetime.utcnow().isoformat()
    if update_approval_status(approval_id, "approved", approved_at):
        return {
            "approval_id": approval_id,
            "status": "approved",
            "message": "Change approved. It can now be applied.",
        }
    return {
        "approval_id": approval_id,
        "status": "not_found",
        "message": "Approval request not found.",
    }
