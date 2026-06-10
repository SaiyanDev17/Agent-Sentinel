"""
Agent Sentinel — FastAPI Backend
==========================================
Main application entry point. Serves the API endpoints that
Agent Builder calls as tools, and hosts the dashboard.

Run with:
    uvicorn api.main:app --reload --port 8000

Then open:
    http://localhost:8000        → Dashboard
    http://localhost:8000/docs   → OpenAPI spec (Agent Builder reads this)
    http://localhost:8000/health → Health check
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# MCP server (Streamable HTTP transport for Google Agent Builder)
from api.mcp_server import mcp_server

# Load environment variables BEFORE importing anything else
load_dotenv()

from api.routes import router
from tools.phoenix_tools import setup_phoenix_tracing

# ── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-15s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ── Startup / Shutdown ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, clean up on shutdown."""
    # ── Startup ──
    logger.info("=" * 60)
    logger.info("Agent Sentinel — Starting up")
    logger.info("=" * 60)

    # Auto-initialize Phoenix tracing
    tracing_result = setup_phoenix_tracing()
    logger.info(f"Phoenix tracing: {tracing_result.get('status', 'unknown')}")

    logger.info("All endpoints available at /tools/*")
    logger.info("MCP server at /mcp (Streamable HTTP)")
    logger.info("OpenAPI spec at /docs")
    logger.info("Dashboard at /")
    logger.info("=" * 60)

    yield  # App is running

    # ── Shutdown ──
    logger.info("Agent Sentinel — Shutting down")


# ── App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Agent Sentinel",
    description=(
        "API backend for the Agent Sentinel QA system.\n\n"
        "**Agent Builder calls these endpoints as OpenAPI tools** to:\n"
        "- Run adversarial scenarios against AidAssist\n"
        "- Score agent responses for safety, privacy, and tool use\n"
        "- Inspect traces in Arize Phoenix via MCP\n"
        "- Manage human approval workflows\n"
        "- Calculate release-readiness scores\n\n"
        "Built for the Google Cloud Rapid Agent Hackathon — Arize Track."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Agent Builder, dashboard, and Cloud Run to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes under /tools prefix
app.include_router(router, prefix="/tools", tags=["Tools"])

# ── MCP Server (Streamable HTTP for Google Agent Builder) ──────────
# Agent Builder connects to /mcp to discover and call tools
app.mount("/mcp", mcp_server.streamable_http_app())


# ── Health Check (outside /tools so load balancers can reach it) ────

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for Cloud Run and load balancers."""
    return {
        "status": "healthy",
        "service": "agent-sentinel",
        "version": "1.0.0",
    }


# ── Serve Dashboard ────────────────────────────────────────────────
# Static files MUST be mounted LAST — it catches all unmatched routes

dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(dashboard_path):
    app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
