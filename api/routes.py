"""
API Routes
==========
All endpoints that Agent Builder calls as OpenAPI tools.
Each endpoint wraps a function from the tools/ directory.

Endpoint Groups:
    /tools/register-aid         — AidAssist target agent tools
    /tools/run-scenario         — Red-team scenario execution
    /tools/score-response       — Evaluation and scoring
    /tools/get-traces           — Phoenix trace inspection
    /tools/request-approval     — Human approval workflow
    /tools/load-scenarios       — Load test scenarios from JSON files
"""

import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Import tool functions
from tools.aid_assist_tools import (
    register_aid_request,
    lookup_shelter,
    escalate_to_human,
    check_aid_status,
    get_all_requests,
)
from tools.phoenix_tools import (
    setup_phoenix_tracing,
    get_recent_traces,
    get_trace_details,
    run_scenario_with_tracing,
    save_scenario_to_dataset,
    save_eval_result,
    get_experiment_comparison,
    update_prompt_in_phoenix,
)
from tools.eval_tools import (
    score_agent_response,
    calculate_release_score,
    detect_failure_patterns,
)
from tools.approval_tools import (
    request_human_approval,
    apply_approved_improvement,
    get_pending_approvals,
    approve_request,
)

router = APIRouter()

# Path to scenario JSON files
SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")


# ── Request/Response Models ─────────────────────────────────────────

class RunScenarioRequest(BaseModel):
    """A single adversarial test scenario."""
    scenario_id: str = Field(description="Unique ID for this scenario")
    category: str = Field(description="Category: prompt_injection, privacy, unsafe_tool_call, etc.")
    user_message: str = Field(description="The message to send to the target agent")
    expected_behavior: str = Field(description="What the agent SHOULD do")
    critical: bool = Field(default=False, description="Whether this is a critical safety test")

class RunScenarioWithTracingRequest(BaseModel):
    """Run result to save to Phoenix with tracing."""
    scenario: dict = Field(description="The test scenario that was run")
    target_agent_response: str = Field(default="", description="What AidAssist actually said")
    tool_calls_made: list[dict] = Field(default_factory=list, description="Tools the agent called")

class ScoreRequest(BaseModel):
    """Request to score an agent response against a scenario."""
    scenario: dict = Field(description="The test scenario with expected_behavior")
    agent_response: str = Field(description="The target agent's actual text response")
    tool_calls: list[dict] = Field(default_factory=list, description="Tool calls the agent made")

class ApprovalRequest(BaseModel):
    """Request to create a human approval for a proposed change."""
    action: str = Field(description="What change is proposed, e.g. 'update_system_prompt'")
    reason: str = Field(description="Why this change is needed, linked to failure evidence")
    risk: str = Field(default="medium", description="Risk level: low, medium, high")
    proposed_change: str = Field(default="", description="The actual content of the proposed change")

class ApplyImprovementRequest(BaseModel):
    """Request to apply a human-approved improvement."""
    approval_id: str = Field(description="The APR-XXXXXXXX approval ID")
    prompt_patch: str = Field(default="", description="New prompt content to apply")

class PromptUpdateRequest(BaseModel):
    """Request to save a prompt version to Phoenix."""
    name: str = Field(description="Prompt template name, e.g. 'aidassist_system_prompt_v2'")
    content: str = Field(description="The full prompt content")

class AidRegistrationRequest(BaseModel):
    """Request to register a new disaster aid request."""
    name: str = Field(description="Full name of the person requesting aid")
    location: str = Field(description="Current location or address")
    aid_type: str = Field(description="Type of aid: shelter, food, transport, or medicine")
    urgency: str = Field(default="normal", description="Urgency: low, normal, high, or critical")

class EscalationRequest(BaseModel):
    """Request to escalate a case to a human operator."""
    reason: str = Field(description="Why this case needs human attention")
    urgency_level: str = Field(default="high", description="Urgency: medium, high, or critical")


# ════════════════════════════════════════════════════════════════════
# 1. AIDASSIST TARGET AGENT TOOLS
# ════════════════════════════════════════════════════════════════════

@router.post("/register-aid", summary="Register disaster aid request")
async def api_register_aid(req: AidRegistrationRequest):
    """Register a new disaster aid request.
    Called by the AidAssist agent when a user needs shelter, food, transport, or medicine."""
    return register_aid_request(req.name, req.location, req.aid_type, req.urgency)

@router.get("/lookup-shelter/{location}", summary="Find nearby shelters")
async def api_lookup_shelter(location: str):
    """Find nearby shelters by location.
    Returns a list of shelters with capacity, occupancy, and facilities."""
    return lookup_shelter(location)

@router.post("/escalate", summary="Escalate to human operator")
async def api_escalate(req: EscalationRequest):
    """Escalate a case to a human operator.
    MUST be called for medical emergencies, unaccompanied minors, safety threats."""
    return escalate_to_human(req.reason, req.urgency_level)

@router.get("/check-status/{request_id}", summary="Check aid request status")
async def api_check_status(request_id: str):
    """Check the status of an existing aid request by its AID-XXXXXXXX ID."""
    return check_aid_status(request_id)

@router.get("/dashboard-data", summary="Get all data for dashboard")
async def api_dashboard_data():
    """Get all aid requests and escalation tickets for dashboard display."""
    return get_all_requests()


# ════════════════════════════════════════════════════════════════════
# 2. SCENARIO MANAGEMENT
# ════════════════════════════════════════════════════════════════════

@router.get("/load-scenarios", summary="Load all test scenarios")
async def api_load_scenarios():
    """Load all adversarial test scenarios from the scenarios/ JSON files.

    Returns all 26 scenarios across 6 categories:
    prompt_injection, privacy, unsafe_tool_call,
    missing_escalation, hallucination, ambiguous_request.
    """
    all_scenarios = []
    categories = {}

    if not os.path.isdir(SCENARIOS_DIR):
        raise HTTPException(status_code=500, detail="Scenarios directory not found")

    for filename in sorted(os.listdir(SCENARIOS_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(SCENARIOS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                scenarios = json.load(f)
                category_name = filename.replace(".json", "")
                categories[category_name] = len(scenarios)
                all_scenarios.extend(scenarios)
        except Exception as e:
            categories[filename] = f"error: {e}"

    return {
        "total_scenarios": len(all_scenarios),
        "categories": categories,
        "scenarios": all_scenarios,
    }

@router.get("/load-scenarios/{category}", summary="Load scenarios by category")
async def api_load_scenarios_by_category(category: str):
    """Load test scenarios for a specific category.

    Valid categories: prompt_injection, privacy_leak, unsafe_tool_call,
    missing_escalation, hallucination, ambiguous_request.
    """
    # Sanitize to prevent path traversal
    safe_category = os.path.basename(category)
    filepath = os.path.abspath(os.path.join(SCENARIOS_DIR, f"{safe_category}.json"))
    
    if not filepath.startswith(os.path.abspath(SCENARIOS_DIR)):
        raise HTTPException(
            status_code=400,
            detail="Invalid category path request."
        )

    if not os.path.isfile(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"Category '{safe_category}' not found. "
                   f"Valid: prompt_injection, privacy_leak, unsafe_tool_call, "
                   f"missing_escalation, hallucination, ambiguous_request",
        )
    with open(filepath, "r", encoding="utf-8") as f:
        scenarios = json.load(f)
    return {
        "category": safe_category,
        "count": len(scenarios),
        "scenarios": scenarios,
    }


# ════════════════════════════════════════════════════════════════════
# 3. PHOENIX TRACING & MCP
# ════════════════════════════════════════════════════════════════════

@router.post("/init-tracing", summary="Initialize Phoenix tracing")
async def api_init_tracing():
    """Initialize OpenInference tracing to Arize Phoenix.
    Called automatically at startup — only needed manually if tracing failed."""
    return setup_phoenix_tracing()

@router.post("/run-scenario", summary="Run scenario with tracing")
async def api_run_scenario(req: RunScenarioWithTracingRequest):
    """Record a scenario run result and save trace data to Phoenix.
    Called AFTER AidAssist has responded to a scenario."""
    return await run_scenario_with_tracing(
        scenario=req.scenario,
        target_agent_response=req.target_agent_response,
        tool_calls_made=req.tool_calls_made,
    )

@router.get("/get-traces", summary="Get recent Phoenix traces")
async def api_get_traces(limit: int = 20):
    """Fetch recent traces from Arize Phoenix.
    The Trace Investigator agent calls this to find failed runs."""
    return await get_recent_traces(limit)

@router.get("/get-trace/{trace_id}", summary="Get trace details")
async def api_get_trace(trace_id: str):
    """Get detailed spans and failures for a specific trace.
    Shows every LLM call, tool call, and response in order."""
    return await get_trace_details(trace_id)

@router.post("/save-to-phoenix", summary="Save scenario to Phoenix dataset")
async def api_save_scenario(scenario: dict):
    """Save a test scenario to a Phoenix dataset for future experiments."""
    return await save_scenario_to_dataset(scenario)

@router.post("/save-eval", summary="Save evaluation to Phoenix")
async def api_save_eval(result: dict):
    """Save an evaluation score to Phoenix as span annotations."""
    return await save_eval_result(result)

@router.get("/get-comparison", summary="Compare before/after experiments")
async def api_get_comparison(exp1_id: str, exp2_id: str):
    """Compare before/after experiment scores.
    The Release Manager agent calls this to see if improvements helped."""
    return await get_experiment_comparison(exp1_id, exp2_id)

@router.post("/update-prompt", summary="Save prompt version to Phoenix")
async def api_update_prompt(req: PromptUpdateRequest):
    """Save an improved prompt version to Phoenix prompt registry.
    Called after human approval of an improvement."""
    return await update_prompt_in_phoenix(req.name, req.content)


# ════════════════════════════════════════════════════════════════════
# 4. EVALUATION & SCORING
# ════════════════════════════════════════════════════════════════════

@router.post("/score-response", summary="Score agent response")
async def api_score_response(req: ScoreRequest):
    """Score a single agent response against a scenario's expected behavior.
    Returns pass/fail scores for safety, privacy, tool use, escalation, groundedness."""
    return score_agent_response(req.scenario, req.agent_response, req.tool_calls)

@router.post("/get-release-score", summary="Calculate release-readiness")
async def api_release_score(all_scores: list[dict]):
    """Aggregate all scenario scores into an overall release-readiness percentage.
    The Release Manager agent calls this to decide if the agent is safe to deploy."""
    return calculate_release_score(all_scores)

@router.post("/detect-patterns", summary="Detect failure patterns")
async def api_detect_patterns(all_results: list[dict]):
    """Cluster recurring failure types across all test results.
    The Failure Pattern agent calls this to find systemic weaknesses."""
    return detect_failure_patterns(all_results)


# ════════════════════════════════════════════════════════════════════
# 5. HUMAN APPROVAL WORKFLOW
# ════════════════════════════════════════════════════════════════════

@router.post("/request-approval", summary="Request human approval")
async def api_request_approval(req: ApprovalRequest):
    """Create an approval request for a proposed improvement.
    No changes are applied to the target agent without human approval."""
    return request_human_approval(req.action, req.reason, req.risk, req.proposed_change)

@router.post("/apply-improvement", summary="Apply approved improvement")
async def api_apply_improvement(req: ApplyImprovementRequest):
    """Apply a human-approved improvement to the target agent.
    Will fail if the approval hasn't been granted yet."""
    return apply_approved_improvement(req.approval_id, req.prompt_patch)

@router.get("/pending-approvals", summary="Get pending approvals")
async def api_pending_approvals():
    """Get all pending approval requests waiting for human review."""
    return get_pending_approvals()

@router.post("/approve/{approval_id}", summary="Approve a change")
async def api_approve(approval_id: str):
    """Approve a pending request. Called from the dashboard UI."""
    return approve_request(approval_id)
