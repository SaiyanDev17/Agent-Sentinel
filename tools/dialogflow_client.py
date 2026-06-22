import os
import uuid
import logging
import threading
import asyncio
from contextlib import contextmanager
from functools import lru_cache

from google.api_core import retry as gcp_retry
from google.cloud import dialogflowcx_v3

logger = logging.getLogger("dialogflow_client")

# Thread-local tracker for parallel scan execution
_local = threading.local()


class TestRunTracker:
    """Captures tool calls per scenario during parallel scans."""

    def __init__(self):
        self._lock = threading.Lock()

    @contextmanager
    def capture(self, scenario_id: str):
        _local.active_scenario_id = scenario_id
        _local.captured_tool_calls = []
        logger.debug("Started capturing tool calls for scenario %s", scenario_id)
        try:
            yield
        finally:
            logger.debug(
                "Stopped capturing for %s (%d tool calls)",
                scenario_id,
                len(_local.captured_tool_calls),
            )
            _local.active_scenario_id = None

    @property
    def active_scenario_id(self):
        return getattr(_local, "active_scenario_id", None)

    @property
    def captured_tool_calls(self) -> list[dict]:
        return getattr(_local, "captured_tool_calls", [])

    def log_tool_call(self, name: str, arguments: dict):
        if getattr(_local, "active_scenario_id", None):
            _local.captured_tool_calls.append({"name": name, "arguments": arguments})


tracker = TestRunTracker()


@lru_cache(maxsize=8)
def _get_sessions_client(api_endpoint: str | None) -> dialogflowcx_v3.SessionsClient:
    """Reuse gRPC client per region endpoint."""
    client_options = {"api_endpoint": api_endpoint} if api_endpoint else None
    return dialogflowcx_v3.SessionsClient(client_options=client_options)


def _resolve_endpoint(location: str) -> tuple[str | None, str]:
    location = location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if location != "global":
        return f"{location}-dialogflow.googleapis.com:443", location
    return None, location


def query_agent(
    text: str,
    project_id: str = None,
    location: str = None,
    agent_id: str = None,
    session_id: str = None,
    timeout: float = 45.0,
) -> str:
    """Send a query to a Dialogflow CX agent (sync, with retries)."""
    project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "agent-sentinel-498916")
    api_endpoint, location = _resolve_endpoint(location or os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))
    agent_id = agent_id or os.getenv("AIDASSIST_AGENT_ID") or os.getenv(
        "DIALOGFLOW_AGENT_ID", "3f4be9c4-06b8-4287-9c38-864e73681191"
    )
    session_id = session_id or f"sentinel_test_{uuid.uuid4().hex[:12]}"

    session_client = _get_sessions_client(api_endpoint)
    session_path = f"projects/{project_id}/locations/{location}/agents/{agent_id}/sessions/{session_id}"

    text_input = dialogflowcx_v3.TextInput(text=text)
    query_input = dialogflowcx_v3.QueryInput(text=text_input, language_code="en")
    request = dialogflowcx_v3.DetectIntentRequest(session=session_path, query_input=query_input)

    retry_policy = gcp_retry.Retry(
        predicate=gcp_retry.if_transient_error,
        initial=0.5,
        maximum=4.0,
        multiplier=2.0,
        deadline=timeout,
    )

    response = session_client.detect_intent(request=request, retry=retry_policy, timeout=timeout)

    text_segments = []
    for message in response.query_result.response_messages:
        if message.text:
            text_segments.append(message.text.text[0])

    agent_response = " ".join(text_segments).strip()
    logger.debug("Dialogflow response (%d chars) for session %s", len(agent_response), session_id)
    return agent_response


async def query_agent_async(
    text: str,
    project_id: str = None,
    location: str = None,
    agent_id: str = None,
    session_id: str = None,
    timeout: float = 45.0,
) -> str:
    """Non-blocking wrapper — runs sync gRPC in a thread pool."""
    return await asyncio.to_thread(
        query_agent,
        text,
        project_id,
        location,
        agent_id,
        session_id,
        timeout,
    )


def query_target_agent(
    text: str,
    project_id: str = None,
    location: str = None,
    agent_id: str = None,
    session_id: str = None,
    timeout: float = 45.0,
) -> str:
    """Send an attack message to the target agent."""
    if agent_id == "aidassist":
        agent_id = os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "hr_assistant":
        agent_id = os.getenv("HR_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "it_helpdesk":
        agent_id = os.getenv("IT_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "finance_advisor":
        agent_id = os.getenv("FINANCE_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")

    agent_id = agent_id or os.getenv("AIDASSIST_AGENT_ID")
    session_id = session_id or f"target_{uuid.uuid4().hex[:12]}"
    return query_agent(
        text=text,
        project_id=project_id,
        location=location,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
    )


async def query_target_agent_async(
    text: str,
    project_id: str = None,
    location: str = None,
    agent_id: str = None,
    session_id: str = None,
    timeout: float = 45.0,
) -> str:
    if agent_id == "aidassist":
        agent_id = os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "hr_assistant":
        agent_id = os.getenv("HR_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "it_helpdesk":
        agent_id = os.getenv("IT_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")
    elif agent_id == "finance_advisor":
        agent_id = os.getenv("FINANCE_AGENT_ID") or os.getenv("AIDASSIST_AGENT_ID")

    agent_id = agent_id or os.getenv("AIDASSIST_AGENT_ID")
    session_id = session_id or f"target_{uuid.uuid4().hex[:12]}"
    return await query_agent_async(
        text=text,
        project_id=project_id,
        location=location,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
    )


def query_qacommander(
    text: str,
    project_id: str = None,
    location: str = None,
    session_id: str = None,
    timeout: float = 60.0,
) -> str:
    agent_id = os.getenv("QACOMMANDER_AGENT_ID")
    if not agent_id:
        raise ValueError("QACOMMANDER_AGENT_ID env var not set")
    session_id = session_id or f"commander_{uuid.uuid4().hex[:12]}"
    return query_agent(
        text=text,
        project_id=project_id,
        location=location,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
    )


async def query_qacommander_async(
    text: str,
    project_id: str = None,
    location: str = None,
    session_id: str = None,
    timeout: float = 60.0,
) -> str:
    return await asyncio.to_thread(
        query_qacommander, text, project_id, location, session_id, timeout
    )
