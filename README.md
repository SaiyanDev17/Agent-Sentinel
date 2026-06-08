# Agent Red-Team Autopilot

> Arize Phoenix-powered agent testing, tracing, and release-readiness system for Gemini agents.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What Is This?

Before a company deploys an AI agent, **Agent Red-Team Autopilot** asks:

> *Can this agent be trusted under messy, adversarial, privacy-sensitive, and high-stakes real-world conditions?*

This is an autonomous multi-agent QA system that:

1. **Generates** adversarial test scenarios (prompt injection, privacy leaks, unsafe tool calls)
2. **Runs** a target Gemini agent against those scenarios
3. **Traces** every run in Arize Phoenix
4. **Inspects** failures using Phoenix MCP
5. **Evaluates** safety, privacy, groundedness, tool use, and escalation
6. **Clusters** recurring failure patterns
7. **Recommends** prompt, tool, and guardrail improvements
8. **Produces** a release-readiness score with before/after comparison

## Track

**Arize** — AI observability, agent tracing, evals, Phoenix MCP, hallucination detection, and self-improving agent workflows.

## Architecture

```
Scenario Library (Prompt Injection + Privacy + Hallucination + Tool Misuse + Escalation)
        |
        v
Red-Team Scenario Generator Agent
        |
        v
Target Gemini Agent (AidAssist — disaster relief demo)
        |
        v
Arize Phoenix (Traces + spans + prompts + tool calls + outputs + evaluations)
        |
        v
Phoenix MCP Server (Trace inspection + failure analysis)
        |
        v
Gemini Multi-Agent QA System on Google Cloud Agent Builder
        |
        +--> QA Commander Agent
        +--> Red-Team Generator Agent
        +--> Eval Judge Agent
        +--> Trace Investigator Agent
        +--> Failure Pattern Agent
        +--> Improvement Planner Agent
        +--> Release Manager Agent
        |
        v
Agent QA Console (Release Score + Failure Clusters + Improvements + Before/After)
```

## Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud account with Agent Builder enabled
- Arize Phoenix account (free tier)

### Setup

```bash
# Clone the repo
git clone https://github.com/YOUR-USERNAME/agent-red-team-autopilot.git
cd agent-red-team-autopilot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run the backend
uvicorn api.main:app --reload --port 8000
```

### Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Google Cloud Console → Project ID |
| `GOOGLE_CLOUD_LOCATION` | Usually `us-central1` |
| `PHOENIX_API_KEY` | Arize Phoenix → Settings → API Keys |
| `PHOENIX_BASE_URL` | Usually `https://app.phoenix.arize.com` |

## Project Structure

```
agent-red-team-autopilot/
├── README.md
├── LICENSE
├── requirements.txt
├── .env.example
├── .gitignore
├── tools/
│   ├── aid_assist_tools.py     # AidAssist tool functions
│   ├── phoenix_tools.py        # Phoenix MCP wrapper functions
│   ├── eval_tools.py           # Scoring/evaluation functions
│   └── approval_tools.py       # Human approval gate functions
├── scenarios/
│   ├── prompt_injection.json
│   ├── privacy_leak.json
│   ├── unsafe_tool_call.json
│   ├── missing_escalation.json
│   ├── hallucination.json
│   └── ambiguous_request.json
├── api/
│   ├── main.py                 # FastAPI app
│   └── routes.py               # All API endpoints
├── dashboard/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── deploy/
│   └── Dockerfile
└── docs/
    ├── agent-builder-setup.md
    └── demo-script.md
```

## Tech Stack

- **Google Cloud Agent Builder** — Agent orchestration
- **Gemini** — AI reasoning (target agent + QA agents)
- **Arize Phoenix** — Tracing and observability
- **Phoenix MCP** — Programmatic trace inspection
- **FastAPI** — Tool backend API
- **Cloud Run** — Deployment
- **OpenInference** — Instrumentation

## Hackathon

**Google Cloud Rapid Agent Hackathon** — Arize Track

## License

MIT License — see [LICENSE](LICENSE) for details.
