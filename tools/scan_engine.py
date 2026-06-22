"""
Parallel scan execution engine for Agent Sentinel.

Runs independent scenarios concurrently (bounded by SCAN_CONCURRENCY),
offloads blocking Dialogflow/Gemini/SQLite calls to threads, and emits
progress events for SSE/NDJSON consumers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Awaitable

from opentelemetry import trace

from tools.cache import get_eval_cache, set_eval_cache, get_scenario_cache, set_scenario_cache
from tools.dialogflow_client import query_target_agent_async, tracker
from tools.eval_tools import score_agent_response_async, calculate_release_score
from tools.job_queue import ScanJob, JobStatus
from tools.phoenix_tools import get_tracer_provider, record_local_trace, save_eval_result
from tools.scenario_loader import load_all_scenarios

logger = logging.getLogger("scan_engine")

SCAN_CONCURRENCY = int(os.getenv("SCAN_CONCURRENCY", "4"))
DIALOGFLOW_TIMEOUT = float(os.getenv("DIALOGFLOW_TIMEOUT_SECONDS", "45"))
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))

# Category -> user-facing agent labels for progress UI
CATEGORY_AGENTS = {
    "prompt_injection": "Jailbreaker",
    "privacy": "PII Sniffer",
    "toxicity": "Toxicity Troll",
    "off_topic": "Off-Topic Distractor",
    "unsafe_tool_call": "Tool Abuse Scanner",
    "missing_escalation": "Escalation Probe",
    "hallucination": "Hallucination Hunter",
    "ambiguous_request": "Ambiguity Tester",
}


def _agent_display_name(target_id: str) -> str:
    agent_display_map = {
        "aidassist": "AidAssist",
        "hr_assistant": "HR Assistant",
        "it_helpdesk": "IT Helpdesk",
        "finance_advisor": "Finance Advisor",
    }
    if target_id in agent_display_map:
        return agent_display_map[target_id]
    if len(target_id) > 15:
        return f"Custom ({target_id[:8]})"
    return target_id


def _category_agent(category: str) -> str:
    return CATEGORY_AGENTS.get(category, category.replace("_", " ").title())


EventCallback = Callable[[dict], Awaitable[None] | None]


async def _load_scenarios(params: dict, emit: EventCallback) -> list[dict]:
    agent_description = (params.get("agent_description") or "").strip()
    attack_vector = params.get("attack_vector") or "all"

    if agent_description:
        await emit(
            {
                "status": "processing",
                "index": 0,
                "total": 12,
                "scenario_id": "setup",
                "category": "setup",
                "agent": "Red-Team Generator",
                "message": "Generating custom adversarial safety scenarios...",
                "agents_completed": [],
            }
        )
        try:
            from tools.scenario_generator import generate_scenarios_via_cx_async

            scenarios = await generate_scenarios_via_cx_async(agent_description, attack_vector)
        except Exception as exc:
            logger.error("Dynamic scenario generation failed: %s", exc)
            scenarios = []
        if scenarios:
            return scenarios
        await emit(
            {
                "status": "processing",
                "index": 0,
                "total": 26,
                "scenario_id": "setup",
                "category": "setup",
                "agent": "System",
                "message": "Dynamic generation failed. Using default static scenarios.",
                "agents_completed": [],
            }
        )

    cached = get_scenario_cache()
    if cached:
        return cached.get("scenarios", [])

    data = await asyncio.to_thread(load_all_scenarios)
    set_scenario_cache(data)
    return data.get("scenarios", [])


async def _run_single_scenario(
    scenario: dict,
    idx: int,
    total: int,
    params: dict,
    agent_display_name: str,
    semaphore: asyncio.Semaphore,
    emit: EventCallback,
    completed_agents: set[str],
    agents_lock: asyncio.Lock | None = None,
) -> dict | None:
    scenario_id = scenario.get("scenario_id", f"scenario_{idx}")
    category = scenario.get("category", "")
    user_message = scenario.get("user_message", "")
    category_agent = _category_agent(category)

    async with semaphore:
        agents_completed = list(completed_agents)

        await emit(
            {
                "status": "processing",
                "index": idx,
                "total": total,
                "scenario_id": scenario_id,
                "category": category,
                "agent": category_agent,
                "phase": "attack",
                "message": f"[{idx}/{total}] {category_agent} running attack vector...",
                "agents_completed": agents_completed,
            }
        )

        tp = get_tracer_provider()
        otel_tracer = (
            tp.get_tracer("agent-sentinel") if tp else trace.get_tracer("agent-sentinel")
        )

        trace_id = None
        agent_response = ""
        tool_calls: list[dict] = []
        scenario_start = time.perf_counter()

        with otel_tracer.start_as_current_span("run_test_scenario") as span:
            span.set_attribute("input.value", user_message[:500])
            span.set_attribute("scenario_id", scenario_id)
            span.set_attribute("category", category)
            span.set_attribute("openinference.span.kind", "CHAIN")

            query_start = time.perf_counter()
            try:
                with tracker.capture(scenario_id):
                    agent_response = await query_target_agent_async(
                        text=user_message,
                        project_id=params.get("project_id"),
                        location=params.get("location"),
                        agent_id=params.get("target_agent_id") or params.get("engine_id"),
                        timeout=DIALOGFLOW_TIMEOUT,
                    )
                    tool_calls = list(tracker.captured_tool_calls)
            except Exception as exc:
                logger.error("Dialogflow query failed for %s: %s", scenario_id, exc)
                agent_response = f"Agent failed to respond: {exc}"
                span.record_exception(exc)

            query_duration_ms = int((time.perf_counter() - query_start) * 1000)
            span.set_attribute("output.value", agent_response[:500])
            span.set_attribute("dialogflow.duration_ms", query_duration_ms)
            if tool_calls:
                span.set_attribute("tool_calls.count", len(tool_calls))
                span.set_attribute("tool_calls.names", json.dumps([t.get("name") for t in tool_calls]))

            raw_trace_id = format(span.get_span_context().trace_id, "032x")
            trace_id = raw_trace_id if raw_trace_id.strip("0") else f"local_{uuid.uuid4().hex}"

        local_spans = [
            {
                "span_id": f"{scenario_id}-run",
                "name": "run_test_scenario",
                "span_kind": "CHAIN",
                "status": "OK",
                "duration_ms": int((time.perf_counter() - scenario_start) * 1000),
                "input": user_message,
                "output": agent_response,
                "error": None,
            }
        ]
        record_local_trace(trace_id, local_spans)

        if category_agent not in completed_agents:
            if agents_lock:
                async with agents_lock:
                    completed_agents.add(category_agent)
            else:
                completed_agents.add(category_agent)

        agents_list = list(completed_agents)

        await emit(
            {
                "status": "agent_completed",
                "index": idx,
                "total": total,
                "scenario_id": scenario_id,
                "category": category,
                "agent": category_agent,
                "message": f"✓ {category_agent} completed",
                "agents_completed": agents_list,
            }
        )

        await emit(
            {
                "status": "processing",
                "index": idx,
                "total": total,
                "scenario_id": scenario_id,
                "category": category,
                "agent": f"Target Agent ({agent_display_name})",
                "phase": "target",
                "message": f"[{idx}/{total}] Target agent responded in {query_duration_ms}ms",
                "agents_completed": agents_list,
            }
        )

        await emit(
            {
                "status": "processing",
                "index": idx,
                "total": total,
                "scenario_id": scenario_id,
                "category": category,
                "agent": "Eval Judge",
                "phase": "eval",
                "message": f"[{idx}/{total}] Grading security/compliance rules...",
                "agents_completed": agents_list,
            }
        )

        cached_scores = get_eval_cache(scenario, agent_response)
        if cached_scores:
            scores = dict(cached_scores)
            scores["source"] = "cache"
        else:
            scores = await score_agent_response_async(
                scenario, agent_response, tool_calls, timeout=GEMINI_TIMEOUT
            )
            set_eval_cache(scenario, agent_response, scores)

        if trace_id:
            scores["trace_id"] = trace_id

        await save_eval_result(scores)

        await emit(
            {
                "status": "test_completed",
                "index": idx,
                "total": total,
                "scenario_id": scenario_id,
                "category": category,
                "trace_id": trace_id,
                "user_message": scenario.get("user_message", ""),
                "expected_behavior": scenario.get("expected_behavior", ""),
                "verdict": scores.get("overall", "fail"),
                "reason": scores.get("reason", ""),
                "message": f"[{idx}/{total}] Verdict: {scores.get('overall', 'fail').upper()}",
                "agents_completed": list(completed_agents),
            }
        )
        return scores


async def run_scan_job(job: ScanJob, emit: EventCallback) -> None:
    """Execute a full scan job with parallel scenario processing."""
    params = job.params
    target_id_str = params.get("target_agent_id") or "aidassist"
    agent_display_name = _agent_display_name(target_id_str)

    scenarios = await _load_scenarios(params, emit)
    total = len(scenarios)
    if not scenarios:
        await emit({"status": "error", "message": "Failed to load safety audit scenarios."})
        job.status = JobStatus.FAILED
        return

    await emit(
        {
            "status": "processing",
            "index": 0,
            "total": total,
            "scenario_id": "setup",
            "category": "setup",
            "agent": "Scan Orchestrator",
            "message": f"Starting parallel scan of {total} scenarios (concurrency={SCAN_CONCURRENCY})",
            "agents_completed": [],
        }
    )

    semaphore = asyncio.Semaphore(SCAN_CONCURRENCY)
    completed_agents: set[str] = set()
    agents_lock = asyncio.Lock()
    all_scores: list[dict] = []
    lock = asyncio.Lock()

    async def run_indexed(idx: int, scenario: dict) -> dict | None:
        local_completed = completed_agents

        async def emit_with_agents(event: dict) -> None:
            async with agents_lock:
                event["agents_completed"] = list(completed_agents)
            await emit(event)

        result = await _run_single_scenario(
            scenario,
            idx,
            total,
            params,
            agent_display_name,
            semaphore,
            emit_with_agents,
            local_completed,
            agents_lock,
        )
        if result:
            async with lock:
                all_scores.append(result)
        return result

    tasks = [run_indexed(i + 1, sc) for i, sc in enumerate(scenarios)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            logger.error("Scenario task failed: %s", r)

    release_score = calculate_release_score(all_scores)

    try:
        tp = get_tracer_provider()
        if tp and hasattr(tp, "force_flush"):
            await asyncio.to_thread(tp.force_flush, 2000)
    except Exception as exc:
        logger.warning("OTEL flush failed: %s", exc)

    from tools.phoenix_tools import flush_phoenix_eval_batch

    await asyncio.to_thread(flush_phoenix_eval_batch)

    job.release_score = release_score
    await emit(
        {
            "status": "complete",
            "release_score": release_score,
            "message": (
                f"Safety audit completed! Release Readiness: "
                f"{release_score.get('overall_release_score', 0.0)}%"
            ),
            "agents_completed": list(completed_agents),
        }
    )


async def run_scan_stream(params: dict, emit: EventCallback) -> dict:
    """Run scan inline (for legacy NDJSON streaming endpoint)."""
    job = ScanJob(job_id="inline", params=params)
    await run_scan_job(job, emit)
    return job.release_score or {}
