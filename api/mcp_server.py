"""
MCP Server — Streamable HTTP Transport
=======================================
Wraps all Agent Sentinel tool functions as MCP tools using
the official MCP Python SDK with Streamable HTTP transport.

Google AI Studio Agent Builder connects to /mcp to discover
and call these tools.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Create the MCP server instance
mcp_server = FastMCP(
    "Agent Sentinel Tools",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ════════════════════════════════════════════════════════════════════
# 1. AIDASSIST TARGET AGENT TOOLS
# ════════════════════════════════════════════════════════════════════

@mcp_server.tool()
def register_aid_request(
    name: str,
    location: str,
    aid_type: str,
    urgency: str = "normal",
) -> dict:
    """Register a new disaster aid request.
    Called by AidAssist when a user needs shelter, food, transport, or medicine.

    Args:
        name: Full name of the person requesting aid
        location: Current location or address
        aid_type: Type of aid: shelter, food, transport, or medicine
        urgency: Urgency level: low, normal, high, or critical
    """
    from tools.aid_assist_tools import register_aid_request as _fn
    return _fn(name, location, aid_type, urgency)


@mcp_server.tool()
def lookup_shelter(location: str) -> dict:
    """Find nearby shelters by location.
    Returns a list of shelters with capacity, occupancy, and facilities.

    Args:
        location: Location to search for shelters
    """
    from tools.aid_assist_tools import lookup_shelter as _fn
    return _fn(location)


@mcp_server.tool()
def escalate_to_human(reason: str, urgency_level: str = "high") -> dict:
    """Escalate a case to a human operator.
    MUST be called for medical emergencies, unaccompanied minors, safety threats.

    Args:
        reason: Why this case needs human attention
        urgency_level: Urgency: medium, high, or critical
    """
    from tools.aid_assist_tools import escalate_to_human as _fn
    return _fn(reason, urgency_level)


@mcp_server.tool()
def check_aid_status(request_id: str) -> dict:
    """Check the status of an existing aid request by its AID-XXXXXXXX ID.

    Args:
        request_id: The AID-XXXXXXXX request ID
    """
    from tools.aid_assist_tools import check_aid_status as _fn
    return _fn(request_id)


@mcp_server.tool()
def get_dashboard_data() -> dict:
    """Get all aid requests and escalation tickets for dashboard display."""
    from tools.aid_assist_tools import get_all_requests as _fn
    return _fn()


# ════════════════════════════════════════════════════════════════════
# 2. SCENARIO MANAGEMENT
# ════════════════════════════════════════════════════════════════════

@mcp_server.tool()
def load_all_scenarios() -> dict:
    """Load all adversarial test scenarios from the scenarios/ JSON files.
    Returns all 26 scenarios across 6 categories:
    prompt_injection, privacy, unsafe_tool_call,
    missing_escalation, hallucination, ambiguous_request.
    """
    import os, json
    scenarios_dir = os.path.join(os.path.dirname(__file__), "..", "scenarios")
    all_scenarios = []
    categories = {}

    if not os.path.isdir(scenarios_dir):
        return {"error": "Scenarios directory not found"}

    for filename in sorted(os.listdir(scenarios_dir)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(scenarios_dir, filename)
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


@mcp_server.tool()
def load_scenarios_by_category(category: str) -> dict:
    """Load test scenarios for a specific category.

    Args:
        category: Category name: prompt_injection, privacy_leak, unsafe_tool_call,
                  missing_escalation, hallucination, or ambiguous_request
    """
    import os, json
    scenarios_dir = os.path.join(os.path.dirname(__file__), "..", "scenarios")
    safe_category = os.path.basename(category)
    filepath = os.path.abspath(os.path.join(scenarios_dir, f"{safe_category}.json"))

    if not filepath.startswith(os.path.abspath(scenarios_dir)):
        return {"error": "Invalid category path request."}

    if not os.path.isfile(filepath):
        return {"error": f"Category '{safe_category}' not found."}

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

@mcp_server.tool()
def init_tracing() -> dict:
    """Initialize OpenInference tracing to Arize Phoenix.
    Called automatically at startup — only needed manually if tracing failed.
    """
    from tools.phoenix_tools import setup_phoenix_tracing as _fn
    return _fn()


@mcp_server.tool()
async def run_scenario(
    scenario: dict,
    target_agent_response: str = "",
    tool_calls_made: list[dict] | None = None,
) -> dict:
    """Record a scenario run result and save trace data to Phoenix.
    Called AFTER AidAssist has responded to a scenario.

    Args:
        scenario: The test scenario that was run
        target_agent_response: What AidAssist actually said
        tool_calls_made: Tools the agent called
    """
    from tools.phoenix_tools import run_scenario_with_tracing as _fn
    return await _fn(
        scenario=scenario,
        target_agent_response=target_agent_response,
        tool_calls_made=tool_calls_made or [],
    )


@mcp_server.tool()
async def get_traces(limit: int = 20) -> dict:
    """Fetch recent traces from Arize Phoenix.
    The Trace Investigator agent calls this to find failed runs.

    Args:
        limit: Maximum number of traces to return (default 20)
    """
    from tools.phoenix_tools import get_recent_traces as _fn
    return await _fn(limit)


@mcp_server.tool()
async def get_trace_details(trace_id: str) -> dict:
    """Get detailed spans and failures for a specific trace.
    Shows every LLM call, tool call, and response in order.

    Args:
        trace_id: The trace ID to inspect
    """
    from tools.phoenix_tools import get_trace_details as _fn
    return await _fn(trace_id)


@mcp_server.tool()
async def save_to_phoenix(scenario: dict) -> dict:
    """Save a test scenario to a Phoenix dataset for future experiments.

    Args:
        scenario: The test scenario data to save
    """
    from tools.phoenix_tools import save_scenario_to_dataset as _fn
    return await _fn(scenario)


@mcp_server.tool()
async def save_eval_result(result: dict) -> dict:
    """Save an evaluation score to Phoenix as span annotations.

    Args:
        result: The evaluation result data
    """
    from tools.phoenix_tools import save_eval_result as _fn
    return await _fn(result)


@mcp_server.tool()
async def get_comparison(exp1_id: str, exp2_id: str) -> dict:
    """Compare before/after experiment scores.
    The Release Manager agent calls this to see if improvements helped.

    Args:
        exp1_id: First experiment ID (before)
        exp2_id: Second experiment ID (after)
    """
    from tools.phoenix_tools import get_experiment_comparison as _fn
    return await _fn(exp1_id, exp2_id)


@mcp_server.tool()
async def update_prompt(name: str, content: str) -> dict:
    """Save an improved prompt version to Phoenix prompt registry.
    Called after human approval of an improvement.

    Args:
        name: Prompt template name, e.g. 'aidassist_system_prompt_v2'
        content: The full prompt content
    """
    from tools.phoenix_tools import update_prompt_in_phoenix as _fn
    return await _fn(name, content)


# ════════════════════════════════════════════════════════════════════
# 4. EVALUATION & SCORING
# ════════════════════════════════════════════════════════════════════

@mcp_server.tool()
def score_response(
    scenario: dict,
    agent_response: str,
    tool_calls: list[dict] | None = None,
) -> dict:
    """Score a single agent response against a scenario's expected behavior.
    Returns pass/fail scores for safety, privacy, tool use, escalation, groundedness.

    Args:
        scenario: The test scenario with expected_behavior
        agent_response: The target agent's actual text response
        tool_calls: Tool calls the agent made
    """
    from tools.eval_tools import score_agent_response as _fn
    return _fn(scenario, agent_response, tool_calls or [])


@mcp_server.tool()
def get_release_score(all_scores: list[dict]) -> dict:
    """Aggregate all scenario scores into an overall release-readiness percentage.
    The Release Manager agent calls this to decide if the agent is safe to deploy.

    Args:
        all_scores: List of all scenario score results
    """
    from tools.eval_tools import calculate_release_score as _fn
    return _fn(all_scores)


@mcp_server.tool()
def detect_patterns(all_results: list[dict]) -> dict:
    """Cluster recurring failure types across all test results.
    The Failure Pattern agent calls this to find systemic weaknesses.

    Args:
        all_results: List of all test results to analyze
    """
    from tools.eval_tools import detect_failure_patterns as _fn
    return _fn(all_results)


# ════════════════════════════════════════════════════════════════════
# 5. HUMAN APPROVAL WORKFLOW
# ════════════════════════════════════════════════════════════════════

@mcp_server.tool()
def request_approval(
    action: str,
    reason: str,
    risk: str = "medium",
    proposed_change: str = "",
) -> dict:
    """Create an approval request for a proposed improvement.
    No changes are applied to the target agent without human approval.

    Args:
        action: What change is proposed, e.g. 'update_system_prompt'
        reason: Why this change is needed, linked to failure evidence
        risk: Risk level: low, medium, high
        proposed_change: The actual content of the proposed change
    """
    from tools.approval_tools import request_human_approval as _fn
    return _fn(action, reason, risk, proposed_change)


@mcp_server.tool()
def apply_improvement(approval_id: str, prompt_patch: str = "") -> dict:
    """Apply a human-approved improvement to the target agent.
    Will fail if the approval hasn't been granted yet.

    Args:
        approval_id: The APR-XXXXXXXX approval ID
        prompt_patch: New prompt content to apply
    """
    from tools.approval_tools import apply_approved_improvement as _fn
    return _fn(approval_id, prompt_patch)


@mcp_server.tool()
def get_pending_approvals() -> dict:
    """Get all pending approval requests waiting for human review."""
    from tools.approval_tools import get_pending_approvals as _fn
    return _fn()


@mcp_server.tool()
def approve_change(approval_id: str) -> dict:
    """Approve a pending request. Called from the dashboard UI.

    Args:
        approval_id: The APR-XXXXXXXX approval ID to approve
    """
    from tools.approval_tools import approve_request as _fn
    return _fn(approval_id)


@mcp_server.tool()
def get_evaluations() -> dict:
    """Get all stored scenario evaluation results for dashboard rendering."""
    from tools.db import get_all_evaluations as _fn
    return _fn()
