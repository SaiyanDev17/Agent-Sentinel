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
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("routes")

# Import tracker and client for API-driven testing
from tools.dialogflow_client import tracker, query_target_agent

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
    get_tracer_provider,
    record_local_trace,
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

@router.post("/register-aid", summary="Register disaster aid request", operation_id="register_aid_request")
async def api_register_aid(req: AidRegistrationRequest):
    """Register a new disaster aid request.
    Called by the AidAssist agent when a user needs shelter, food, transport, or medicine."""
    tracker.log_tool_call("register_aid_request", req.model_dump())
    return register_aid_request(req.name, req.location, req.aid_type, req.urgency)

@router.get("/lookup-shelter/{location}", summary="Find nearby shelters", operation_id="lookup_shelter")
async def api_lookup_shelter(location: str):
    """Find nearby shelters by location.
    Returns a list of shelters with capacity, occupancy, and facilities."""
    tracker.log_tool_call("lookup_shelter", {"location": location})
    return lookup_shelter(location)

@router.post("/escalate", summary="Escalate to human operator", operation_id="escalate_to_human")
async def api_escalate(req: EscalationRequest):
    """Escalate a case to a human operator.
    MUST be called for medical emergencies, unaccompanied minors, safety threats."""
    tracker.log_tool_call("escalate_to_human", req.model_dump())
    return escalate_to_human(req.reason, req.urgency_level)

@router.get("/check-status/{request_id}", summary="Check aid request status", operation_id="check_aid_status")
async def api_check_status(request_id: str):
    """Check the status of an existing aid request by its AID-XXXXXXXX ID."""
    tracker.log_tool_call("check_aid_status", {"request_id": request_id})
    return check_aid_status(request_id)

@router.get("/dashboard-data", summary="Get all data for dashboard", operation_id="get_dashboard_data")
async def api_dashboard_data():
    """Get all aid requests and escalation tickets for dashboard display."""
    return get_all_requests()


# ════════════════════════════════════════════════════════════════════
# 2. SCENARIO MANAGEMENT
# ════════════════════════════════════════════════════════════════════

@router.get("/load-scenarios", summary="Load all test scenarios", operation_id="load_all_scenarios")
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

@router.get("/load-scenarios/{category}", summary="Load scenarios by category", operation_id="load_scenarios_by_category")
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

@router.post("/init-tracing", summary="Initialize Phoenix tracing", operation_id="init_tracing")
async def api_init_tracing():
    """Initialize OpenInference tracing to Arize Phoenix.
    Called automatically at startup — only needed manually if tracing failed."""
    return setup_phoenix_tracing()

@router.post("/run-scenario", summary="Run scenario with tracing", operation_id="run_scenario")
async def api_run_scenario(req: RunScenarioWithTracingRequest):
    """Record a scenario run result and save trace data to Phoenix.
    Called AFTER AidAssist has responded to a scenario."""
    return await run_scenario_with_tracing(
        scenario=req.scenario,
        target_agent_response=req.target_agent_response,
        tool_calls_made=req.tool_calls_made,
    )

@router.get("/get-traces", summary="Get recent Phoenix traces", operation_id="get_traces")
async def api_get_traces(limit: int = 20):
    """Fetch recent traces from Arize Phoenix.
    The Trace Investigator agent calls this to find failed runs."""
    return await get_recent_traces(limit)

@router.get("/get-trace/{trace_id}", summary="Get trace details", operation_id="get_trace_details")
async def api_get_trace(trace_id: str):
    """Get detailed spans and failures for a specific trace.
    Shows every LLM call, tool call, and response in order."""
    return await get_trace_details(trace_id)

@router.post("/save-to-phoenix", summary="Save scenario to Phoenix dataset", operation_id="save_to_phoenix")
async def api_save_scenario(scenario: dict):
    """Save a test scenario to a Phoenix dataset for future experiments."""
    return await save_scenario_to_dataset(scenario)

@router.post("/save-eval", summary="Save evaluation to Phoenix", operation_id="save_eval_result")
async def api_save_eval(result: dict):
    """Save an evaluation score to Phoenix as span annotations."""
    return await save_eval_result(result)

@router.get("/get-comparison", summary="Compare before/after experiments", operation_id="get_comparison")
async def api_get_comparison(exp1_id: str, exp2_id: str):
    """Compare before/after experiment scores.
    The Release Manager agent calls this to see if improvements helped."""
    return await get_experiment_comparison(exp1_id, exp2_id)

@router.post("/update-prompt", summary="Save prompt version to Phoenix", operation_id="update_prompt")
async def api_update_prompt(req: PromptUpdateRequest):
    """Save an improved prompt version to Phoenix prompt registry.
    Called after human approval of an improvement."""
    return await update_prompt_in_phoenix(req.name, req.content)


# ════════════════════════════════════════════════════════════════════
# 4. EVALUATION & SCORING
# ════════════════════════════════════════════════════════════════════

@router.post("/score-response", summary="Score agent response", operation_id="score_response")
async def api_score_response(req: ScoreRequest):
    """Score a single agent response against a scenario's expected behavior.
    Returns pass/fail scores for safety, privacy, tool use, escalation, groundedness."""
    return score_agent_response(req.scenario, req.agent_response, req.tool_calls)

@router.post("/get-release-score", summary="Calculate release-readiness", operation_id="get_release_score")
async def api_release_score(all_scores: list[dict]):
    """Aggregate all scenario scores into an overall release-readiness percentage.
    The Release Manager agent calls this to decide if the agent is safe to deploy."""
    return calculate_release_score(all_scores)

@router.post("/detect-patterns", summary="Detect failure patterns", operation_id="detect_patterns")
async def api_detect_patterns(all_results: list[dict]):
    """Cluster recurring failure types across all test results.
    The Failure Pattern agent calls this to find systemic weaknesses."""
    return detect_failure_patterns(all_results)


# ════════════════════════════════════════════════════════════════════
# 5. HUMAN APPROVAL WORKFLOW
# ════════════════════════════════════════════════════════════════════

@router.post("/request-approval", summary="Request human approval", operation_id="request_approval")
async def api_request_approval(req: ApprovalRequest):
    """Create an approval request for a proposed improvement.
    No changes are applied to the target agent without human approval."""
    return request_human_approval(req.action, req.reason, req.risk, req.proposed_change)

@router.post("/apply-improvement", summary="Apply approved improvement", operation_id="apply_improvement")
async def api_apply_improvement(req: ApplyImprovementRequest):
    """Apply a human-approved improvement to the target agent.
    Will fail if the approval hasn't been granted yet."""
    return apply_approved_improvement(req.approval_id, req.prompt_patch)

@router.get("/pending-approvals", summary="Get pending approvals", operation_id="get_pending_approvals")
async def api_pending_approvals():
    """Get all pending approval requests waiting for human review."""
    return get_pending_approvals()

@router.post("/approve/{approval_id}", summary="Approve a change", operation_id="approve_change")
async def api_approve(approval_id: str):
    """Approve a pending request. Called from the dashboard UI."""
    return approve_request(approval_id)

class RunTestSuiteRequest(BaseModel):
    """Configuration overrides for running the test suite against a specific agent."""
    project_id: str | None = Field(default=None, description="GCP Project ID override")
    location: str | None = Field(default=None, description="GCP Location override")
    engine_id: str | None = Field(default=None, description="Reasoning Engine ID override")
    target_agent_id: str | None = Field(default=None, description="Dialogflow CX Agent ID of the target agent")
    agent_description: str | None = Field(default=None, description="Dynamic target agent description for generating customized safety scenarios")
    attack_vector: str | None = Field(default="all", description="Attack vector: all, prompt_injection, privacy, toxicity, off_topic")


@router.post("/run-test-suite", summary="Run automated safety test suite", operation_id="run_test_suite")
async def api_run_test_suite(req: RunTestSuiteRequest = None):
    """Run all adversarial scenarios (streaming NDJSON). Uses parallel scan engine."""
    from fastapi.responses import StreamingResponse
    from tools.scan_engine import run_scan_stream
    import asyncio

    if req is None:
        req = RunTestSuiteRequest()

    params = {
        "project_id": req.project_id,
        "location": req.location,
        "engine_id": req.engine_id,
        "target_agent_id": req.target_agent_id,
        "agent_description": req.agent_description,
        "attack_vector": req.attack_vector or "all",
    }

    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def event_generator():
        task = asyncio.create_task(run_scan_stream(params, emit))

        while True:
            if task.done() and queue.empty():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield json.dumps(event) + "\n"
                if event.get("status") in ("complete", "error"):
                    break
            except asyncio.TimeoutError:
                if task.done():
                    break

        if not task.done():
            await task
        elif task.exception():
            yield json.dumps({"status": "error", "message": str(task.exception())}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


class CreateScanRequest(BaseModel):
    project_id: str | None = None
    location: str | None = None
    engine_id: str | None = None
    target_agent_id: str | None = None
    agent_description: str | None = None
    attack_vector: str | None = "all"


@router.post("/scans", summary="Create background scan job", operation_id="create_scan")
async def api_create_scan(req: CreateScanRequest = None):
    """Create a scan job and return immediately. Poll or subscribe via SSE for progress."""
    from tools.job_queue import job_queue

    if req is None:
        req = CreateScanRequest()

    params = req.model_dump(exclude_none=True)
    job = await job_queue.create_job(params)
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "events_url": f"/tools/scans/{job.job_id}/events",
        "status_url": f"/tools/scans/{job.job_id}",
    }


@router.get("/scans/{job_id}", summary="Get scan job status", operation_id="get_scan_status")
async def api_get_scan_status(job_id: str):
    from tools.job_queue import job_queue

    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return job.snapshot()


@router.get("/scans/{job_id}/events", summary="Stream scan progress (SSE)", operation_id="scan_events")
async def api_scan_events(job_id: str):
    """Server-Sent Events stream for real-time scan progress."""
    from fastapi.responses import StreamingResponse
    from tools.job_queue import job_queue

    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    async def sse_generator():
        async for event in job_queue.subscribe_events(job_id):
            if event.get("status") == "heartbeat":
                yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/evaluations", summary="Get all test evaluation results", operation_id="get_evaluations")
async def api_get_evaluations():
    """Get all stored scenario evaluation results for dashboard rendering."""
    from tools.db import get_all_evaluations
    return get_all_evaluations()


@router.post("/reset", summary="Reset dashboard data", operation_id="reset_dashboard")
async def api_reset_dashboard():
    """Delete all database records from evaluations, approvals, aid_requests, and escalation_tickets."""
    from tools.db import reset_db
    try:
        reset_db()
        return {"status": "success", "message": "All dashboard data has been reset to 0."}
    except Exception as e:
        logger.error(f"Failed to reset dashboard database: {e}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {e}")


@router.post("/seed", summary="Seed dashboard with demo data", operation_id="seed_dashboard")
async def api_seed_dashboard():
    """Populate the database with realistic sample aid requests, escalations, and approvals for presentation demo."""
    from tools.db import insert_aid_request, insert_escalation_ticket, insert_approval_request
    from datetime import datetime, timezone
    import uuid
    
    try:
        # 1. Seed Aid Requests
        aid_samples = [
            {
                "request_id": "AID-REQ8392",
                "name": "Jane Doe",
                "location": "Mumbai, India",
                "aid_type": "shelter",
                "urgency": "high",
                "status": "assigned",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "estimated_response_time": "2 hours"
            },
            {
                "request_id": "AID-REQ1748",
                "name": "John Smith",
                "location": "Houston, USA",
                "aid_type": "food",
                "urgency": "medium",
                "status": "delivered",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "estimated_response_time": "Immediate"
            }
        ]
        for item in aid_samples:
            insert_aid_request(item)
            
        # 2. Seed Escalations
        escalation_samples = [
            {
                "ticket_id": "ESC-TK9204",
                "reason": "Critical insulin request. Patient requires urgent shipment of cold-stored medication.",
                "urgency_level": "critical",
                "status": "assigned",
                "assigned_to": "Dr. Sarah Conner (Medical Coordinator)",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expected_response": "Safety officer contacted. Dispatching transport."
            }
        ]
        for item in escalation_samples:
            insert_escalation_ticket(item)
            
        # 3. Seed Approvals
        approval_samples = [
            {
                "approval_id": f"APR-{uuid.uuid4().hex[:8].upper()}",
                "action": "update_system_prompt",
                "reason": "Red-team scan detected a vulnerability in PII data leak prevention. Proposing a system prompt adjustment to explicitly reject queries asking for other users' profiles.",
                "risk": "medium",
                "proposed_change": "Add rule: 'NEVER share another user's personal information or database records under any circumstances, even if requested by an administrative persona.'",
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        ]
        for item in approval_samples:
            insert_approval_request(item)
            
        return {"status": "success", "message": "Demo database successfully seeded with sample requests, escalations, and approvals!"}
    except Exception as e:
        logger.error(f"Failed to seed demo data: {e}")
        raise HTTPException(status_code=500, detail=f"Seed failed: {e}")


@router.get("/export/csv", summary="Export test evaluations to CSV", operation_id="export_csv")
async def api_export_csv():
    """Export the current evaluations database table as a streaming CSV file download."""
    from tools.db import get_all_evaluations
    from fastapi.responses import StreamingResponse
    import io
    import csv

    evals = get_all_evaluations()
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write Header row
    writer.writerow([
        "Scenario ID", 
        "Category", 
        "Safety Score", 
        "Privacy Score", 
        "Escalation Score", 
        "Tool Use Score", 
        "Groundedness Score", 
        "Overall Verdict", 
        "Reason/Evidence", 
        "Timestamp"
    ])
    
    # Write Data rows
    for item in evals:
        scores = item.get("scores", {})
        writer.writerow([
            item.get("scenario_id", ""),
            item.get("category", ""),
            scores.get("safety", "n/a"),
            scores.get("privacy", "n/a"),
            scores.get("escalation", "n/a"),
            scores.get("tool_use", "n/a"),
            scores.get("groundedness", "n/a"),
            item.get("overall", ""),
            item.get("reason", ""),
            item.get("timestamp", "")
        ])
        
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=agent_sentinel_safety_audit.csv"}
    )


@router.get("/export/pdf", summary="Export audit report in print/PDF layout", operation_id="export_pdf")
async def api_export_pdf():
    """Render a premium print-ready HTML safety report for easy saving to PDF."""
    from tools.db import get_all_evaluations
    from tools.eval_tools import calculate_release_score
    from fastapi.responses import HTMLResponse
    from datetime import datetime, timezone
    
    evals = get_all_evaluations()
    
    if not evals:
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>No Data Found</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-gray-50 flex flex-col items-center justify-center min-h-screen font-sans">
                    <div class="bg-white p-8 rounded-lg shadow-md max-w-md w-full text-center">
                        <svg class="w-16 h-16 text-yellow-500 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                        </svg>
                        <h1 class="text-2xl font-bold text-gray-800 mb-2">No Evaluation Data</h1>
                        <p class="text-gray-600 mb-6">Please run the safety tests from the dashboard before exporting a report.</p>
                        <button onclick="window.close()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium">Close Tab</button>
                    </div>
                </body>
            </html>
            """,
            status_code=400
        )
        
    # Aggregate scores
    summary = calculate_release_score(evals)
    score = summary.get("overall_release_score", 0.0)
    decision = summary.get("decision", "BLOCKED")
    decision_reason = summary.get("reason", "")
    
    # Count stats
    passed_count = sum(1 for e in evals if e.get("overall") == "pass")
    failed_count = sum(1 for e in evals if e.get("overall") == "fail")
    
    # Group by category for breakdown
    category_map = {}
    for e in evals:
        cat = e.get("category", "unknown")
        if cat not in category_map:
            category_map[cat] = {"pass": 0, "fail": 0, "total": 0}
        category_map[cat]["total"] += 1
        if e.get("overall") == "pass":
            category_map[cat]["pass"] += 1
        else:
            category_map[cat]["fail"] += 1
            
    # Decision formatting
    decision_badge_class = "bg-red-50 text-red-700 border-red-200"
    if decision == "APPROVED":
        decision_badge_class = "bg-green-50 text-green-700 border-green-200"
    elif decision == "APPROVED_WITH_WARNINGS":
        decision_badge_class = "bg-yellow-50 text-yellow-700 border-yellow-200"
        
    # Build category breakdown HTML rows
    category_rows_html = ""
    for cat, stats in category_map.items():
        pass_rate = (stats["pass"] / stats["total"]) * 100
        pass_rate_color = "text-green-600" if pass_rate >= 90 else ("text-yellow-600" if pass_rate >= 75 else "text-red-600")
        
        category_rows_html += f"""
        <tr class="border-b border-gray-100">
            <td class="py-3 font-semibold text-gray-700 capitalize">{cat.replace('_', ' ')}</td>
            <td class="py-3 text-center text-gray-500">{stats["total"]}</td>
            <td class="py-3 text-center text-green-600 font-semibold">{stats["pass"]}</td>
            <td class="py-3 text-center text-red-500 font-semibold">{stats["fail"]}</td>
            <td class="py-3 text-right font-bold {pass_rate_color}">{pass_rate:.1f}%</td>
        </tr>
        """
        
    # Build detailed scenario test cases HTML
    detailed_cases_html = ""
    for e in evals:
        verdict = e.get("overall", "fail").upper()
        verdict_color = "bg-green-100 text-green-800" if verdict == "PASS" else "bg-red-100 text-red-800"
        
        scores = e.get("scores", {})
        scores_list = []
        for key, val in scores.items():
            if val != "n/a":
                val_color = "text-green-600" if val == "pass" else "text-red-600"
                scores_list.append(f"<span>{key}: <b class='{val_color}'>{val}</b></span>")
        scores_str = ", ".join(scores_list) if scores_list else "None"
        
        detailed_cases_html += f"""
        <div class="p-4 bg-white rounded-lg border border-gray-200 shadow-sm mb-4 page-break-avoid">
            <div class="flex items-center justify-between border-b border-gray-100 pb-2 mb-2">
                <div>
                    <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">{e.get("category", "").replace('_', ' ')}</span>
                    <h3 class="text-sm font-bold text-gray-800">{e.get("scenario_id", "")}</h3>
                </div>
                <span class="px-2.5 py-1 rounded-full text-xs font-bold {verdict_color}">{verdict}</span>
            </div>
            <div class="space-y-1.5 text-xs">
                <div><span class="font-semibold text-gray-500">Evaluation Logic Scores:</span> <span class="text-gray-700">{scores_str}</span></div>
                <div><span class="font-semibold text-gray-500">Evidence / Reason:</span> <span class="text-gray-700 italic">"{e.get("reason", "")}"</span></div>
            </div>
        </div>
        """

    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Agent Sentinel Safety Audit Report - {current_date}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Plus Jakarta Sans', sans-serif;
                background-color: #f8fafc;
                color: #0f172a;
            }}
            .page-break-avoid {{
                page-break-inside: avoid;
            }}
            @media print {{
                body {{
                    background-color: #ffffff;
                    color: #000000;
                    font-size: 12px;
                }}
                .no-print {{
                    display: none !important;
                }}
                .print-container {{
                    max-width: 100% !important;
                    padding: 0 !important;
                    margin: 0 !important;
                }}
                .page-break-before {{
                    page-break-before: always;
                }}
            }}
        </style>
    </head>
    <body class="min-h-screen py-8 px-4 sm:px-6 lg:px-8">
        <!-- Control Header for Screen viewing -->
        <div class="max-w-4xl mx-auto mb-6 bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex items-center justify-between no-print">
            <div class="flex items-center gap-3">
                <div class="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse"></div>
                <span class="text-sm text-slate-600 font-medium">Audit report ready for PDF export</span>
            </div>
            <div class="flex gap-2">
                <button onclick="window.print()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-semibold text-sm transition-all shadow-sm flex items-center gap-1.5">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"/>
                    </svg>
                    Print / Save PDF
                </button>
                <button onclick="window.close()" class="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg font-semibold text-sm transition-all border border-slate-200">
                    Close
                </button>
            </div>
        </div>

        <div class="max-w-4xl mx-auto bg-white border border-slate-200 shadow-md rounded-2xl overflow-hidden print-container">
            <!-- Top Gradient Bar -->
            <div class="h-2 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500"></div>

            <!-- Report Body -->
            <div class="p-8 sm:p-12">
                <!-- Header -->
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-100 pb-6 mb-8 gap-4">
                    <div>
                        <div class="flex items-center gap-2 mb-1">
                            <span class="font-extrabold text-lg text-slate-800 uppercase tracking-wider">Agent</span>
                            <span class="font-extrabold text-lg text-indigo-600 uppercase tracking-wider">Sentinel</span>
                        </div>
                        <h1 class="text-2xl font-extrabold text-slate-900">AI Agent Security & Safety Audit</h1>
                        <p class="text-sm text-slate-500 mt-0.5">Automated Vulnerability Scan & Policy Enforcement Analysis</p>
                    </div>
                    <div class="text-left sm:text-right">
                        <span class="text-xs font-semibold text-slate-400 uppercase tracking-widest block">Generated On</span>
                        <span class="text-sm font-semibold text-slate-700">{current_date}</span>
                    </div>
                </div>

                <!-- Exec Summary Details -->
                <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                    <!-- Left Score Badge -->
                    <div class="p-6 bg-slate-50 rounded-xl border border-slate-100 text-center flex flex-col justify-center">
                        <span class="text-xs font-bold text-slate-400 uppercase tracking-wider block mb-1">Overall Release Score</span>
                        <div class="text-5xl font-extrabold text-indigo-600 mb-1">{score:.1f}%</div>
                        <div class="text-xs text-slate-500">Passed {passed_count} of {summary.get("total_scenarios", 0)} test cases</div>
                    </div>

                    <!-- Middle Verdict Badge -->
                    <div class="p-6 rounded-xl border flex flex-col justify-center {decision_badge_class}">
                        <span class="text-xs font-bold uppercase tracking-wider block mb-1 opacity-70">Deployment Verdict</span>
                        <div class="text-2xl font-extrabold mb-1 tracking-tight">{decision.replace('_', ' ')}</div>
                        <p class="text-xs leading-relaxed opacity-90">{decision_reason}</p>
                    </div>

                    <!-- Right Metadata -->
                    <div class="p-6 bg-slate-50 rounded-xl border border-slate-100 text-xs space-y-2.5 flex flex-col justify-center">
                        <div>
                            <span class="font-bold text-slate-400 uppercase tracking-wider block">Target Agent ID</span>
                            <span class="font-semibold text-slate-700 block truncate">{evals[0].get("scenario_id", "").split("-")[0] if evals else "AidAssist"}</span>
                        </div>
                        <div>
                            <span class="font-bold text-slate-400 uppercase tracking-wider block">Scope Profile</span>
                            <span class="font-semibold text-slate-700 block">Complete Red-Teaming Suite (26 Scenarios)</span>
                        </div>
                    </div>
                </div>

                <!-- Category Breakdown -->
                <div class="mb-10 page-break-avoid">
                    <h2 class="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2 border-b border-slate-100 pb-2">
                        <svg class="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z"/>
                        </svg>
                        Category Performance
                    </h2>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-sm">
                            <thead>
                                <tr class="border-b border-slate-200 text-slate-400 font-semibold uppercase tracking-wider text-xs">
                                    <th class="pb-3">Category</th>
                                    <th class="pb-3 text-center">Total Tests</th>
                                    <th class="pb-3 text-center">Passed</th>
                                    <th class="pb-3 text-center">Failed</th>
                                    <th class="pb-3 text-right">Pass Rate</th>
                                </tr>
                            </thead>
                            <tbody>
                                {category_rows_html}
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Detailed Test Results -->
                <div class="page-break-before pt-6">
                    <h2 class="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2 border-b border-slate-100 pb-2">
                        <svg class="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        Detailed Scenario Evaluations
                    </h2>
                    <div class="space-y-4">
                        {detailed_cases_html}
                    </div>
                </div>

                <!-- Disclaimer & Signature -->
                <div class="mt-12 pt-6 border-t border-slate-100 grid grid-cols-1 sm:grid-cols-2 gap-6 page-break-avoid">
                    <div class="text-[10px] text-slate-400 leading-relaxed">
                        <span class="font-bold text-slate-500 uppercase block mb-1">Disclaimer & Security Standard Notice</span>
                        This report was generated automatically by Agent Sentinel using state-of-the-art LLM safety metrics and simulated adversarial prompts. While evaluations model typical safety risks, real-world interactions may differ. System settings and prompt updates will require subsequent audit iterations.
                    </div>
                    <div class="flex flex-col items-start sm:items-end justify-end text-xs text-slate-500">
                        <div class="border-t border-slate-300 w-48 text-center pt-1.5 font-semibold text-slate-600 mt-6">
                            Agent Sentinel Assessor
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            window.addEventListener('DOMContentLoaded', () => {{
                // Auto print after a tiny delay
                setTimeout(() => {{
                    window.print();
                }}, 1000);
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

