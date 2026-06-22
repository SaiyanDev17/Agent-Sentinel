# Agent Sentinel — Performance Report

**Date:** June 22, 2026  
**Scope:** Full-stack audit and optimization of the Agent Sentinel red-teaming platform  
**Deployment target:** Google Cloud Run  

---

## Executive Summary

The primary bottleneck was **fully sequential scan execution** inside a long-lived HTTP request. Each of 26 scenarios blocked the event loop on Dialogflow gRPC + Gemini judge calls (~2–9s each), yielding **52s–4min+** total scan time with poor perceived latency.

Implemented fixes deliver an estimated **60–75% reduction in wall-clock scan time** (with `SCAN_CONCURRENCY=4`) and **immediate API response** via background jobs + SSE.

---

## Bottleneck Inventory (Prioritized by Impact)

### P0 — Critical

| # | Bottleneck | Location | Expected Gain |
|---|-----------|----------|---------------|
| 1 | **Sequential scenario loop** — 26 scenarios run one-at-a-time | `api/routes.py` (old `:409–559`) | **60–75% scan time reduction** with parallel execution (`SCAN_CONCURRENCY=4`) |
| 2 | **Blocking sync I/O in async handlers** — Dialogflow gRPC, Gemini, SQLite blocked uvicorn event loop | `dialogflow_client.py`, `eval_tools.py`, `phoenix_tools.py` | **2–5× API throughput**; dashboard stays responsive during scans |
| 3 | **Long-held HTTP connection for entire scan** — Cloud Run request slot tied up for minutes | Old `run-test-suite` streaming | **Instant HTTP return** via job queue; frees concurrency for other users |
| 4 | **New Dialogflow SessionsClient per call** | `dialogflow_client.py:72` (old) | **~100–300ms saved per scenario** (TLS + client init) |

### P1 — High

| # | Bottleneck | Location | Expected Gain |
|---|-----------|----------|---------------|
| 5 | **Gemini model re-init on every eval** — `vertexai.init()` per call | `eval_tools.py:221` (old) | **~200–500ms saved per scenario** |
| 6 | **New Phoenix Client() per operation** | `phoenix_tools.py:191` (old) | **~50–150ms per save/query** |
| 7 | **Phoenix full-project span dataframe load** | `phoenix_tools.py:327` | **90%+ faster trace drill-down** when local cache hit |
| 8 | **SQLite connect/disconnect per write** | `db.py` (old) | **~5–15ms saved per eval insert** |
| 9 | **Phoenix dataset write per eval** | `phoenix_tools.py:603` (old) | **80% fewer Phoenix API calls** via batching (size 5) |
| 10 | **5-second dashboard polling with 3 sequential fetches** | `dashboard/app.js` (old) | **67% fewer poll requests** (15s interval); **3× faster refresh** via `Promise.all` |
| 11 | **Full table DOM rebuild on every scan event** | `dashboard/app.js:791` (old) | **Smoother UI**; reduced GC during 26-scenario scans |

### P2 — Medium

| # | Bottleneck | Location | Expected Gain |
|---|-----------|----------|---------------|
| 12 | **Scenario JSON re-read from disk every scan** | `routes.py:172` (old) | **~10–50ms saved**; preloaded at startup |
| 13 | **Artificial asyncio.sleep pacing** | `routes.py:424,559` (old) | **~1.3s removed** (negligible vs API latency) |
| 14 | **Per-row event listeners on re-render** | `dashboard/app.js` | Reduced listener churn via delegation |
| 15 | **httpx client per agent tool call** | `agent/agent.py` | Connection reuse for webhook tools |
| 16 | **No eval result caching for repeated prompts** | N/A | **Near-instant re-eval** on cache hit (re-runs, dev loops) |
| 17 | **Excessive OTEL child spans per tool call** | `routes.py:493` (old) | **~30% less trace export overhead** |
| 18 | **Cloud Run cold starts** — no min instances, no startup preload | `Dockerfile`, deploy config | **2–5s faster first request** with minScale=1 + cache warmup |
| 19 | **Refresh button stuck disabled after success** | `dashboard/app.js:540` (old) | UX fix — no perf gain but blocked manual refresh |

### P3 — Lower (Not Implemented / Future)

| # | Bottleneck | Notes |
|---|-----------|-------|
| 20 | SQLite on ephemeral Cloud Run disk | Requires Cloud SQL or mounted volume for persistence |
| 21 | No frontend bundler/minification | Vanilla JS; recommend Vite if migrating to React |
| 22 | Font Awesome full CDN load | Subset icons or inline SVGs |
| 23 | Single-process uvicorn | Cloud Run horizontal scaling compensates; avoid multi-worker + in-memory job queue without Redis |

---

## Implemented Fixes

### Backend

| Fix | Module | Description |
|-----|--------|-------------|
| Parallel scan engine | `tools/scan_engine.py` | `asyncio.gather` + `Semaphore(SCAN_CONCURRENCY)` |
| Background job queue | `tools/job_queue.py` | POST `/tools/scans` returns immediately; worker processes async |
| SSE progress stream | `api/routes.py` | GET `/tools/scans/{id}/events` |
| Thread-pool offload | `dialogflow_client.py`, `eval_tools.py` | `asyncio.to_thread()` for blocking APIs |
| Dialogflow client reuse | `dialogflow_client.py` | `@lru_cache` on `SessionsClient` per region |
| Dialogflow retries | `dialogflow_client.py` | `google.api_core.retry` with transient error handling |
| Gemini singleton | `eval_tools.py` | Single model instance; no repeated `vertexai.init()` |
| Eval caching | `tools/cache.py` | SHA-256 keyed cache; Redis-compatible via `REDIS_URL` |
| Phoenix client singleton | `phoenix_tools.py` | One client per process |
| Phoenix eval batching | `phoenix_tools.py` | Batch size 5; flush at scan end |
| Reduced OTEL spans | `scan_engine.py` | One span per scenario; tool calls as attributes |
| SQLite thread-local pool | `db.py` | Reused connections + WAL + indexes |
| Scenario preload | `api/main.py` | Loaded at startup, not per request |
| Shared httpx clients | `tools/http_clients.py`, `agent/agent.py` | Connection pooling |

### Frontend

| Fix | Description |
|-----|-------------|
| Job + SSE flow | `POST /scans` → `EventSource` for real-time updates |
| Agent checklist UI | ✓ Jailbreaker, ✓ PII Sniffer, ⏳ Toxicity Troll |
| Incremental table rows | `appendEvalRow()` instead of full re-render |
| Parallel dashboard fetch | `Promise.all` for 3 endpoints |
| Smart polling | 15s interval; paused during scans; visibility-aware |
| Terminal append | DOM nodes instead of `innerHTML +=` |
| Debounced search | 200ms debounce |
| Event delegation | Trace buttons on `#tbody-test-results` |

### Cloud Run

| Setting | Value | Rationale |
|---------|-------|-----------|
| `minScale` | 1 | Reduce cold starts |
| `containerConcurrency` | 80 | I/O-bound async workload |
| CPU / Memory | 2 vCPU / 2Gi | Supports 4 parallel Dialogflow+Gemini calls |
| `timeoutSeconds` | 3600 | Long scans via background jobs |
| `startup-cpu-boost` | true | Faster Phoenix/scenario init |
| `SCAN_CONCURRENCY` | 4 | Tunable via env |

---

## Performance Model (After Optimization)

For **26 static scenarios** with `SCAN_CONCURRENCY=4`:

```
T_total ≈ T_setup
        + ceil(26 / 4) × (T_dialogflow + T_gemini_judge + T_db)
        + T_release_score + T_otel_flush

Rough estimate:
  Before: 26 × 3–8s  = 78s – 3.5min
  After:   7 × 3–8s  = 21s – 56s   (parallel batches)
  Re-run with cache:  ~30–50% faster on eval step
```

**Perceived latency:**

| Metric | Before | After |
|--------|--------|-------|
| Time to first progress event | 3–8s (blocked on setup) | **<200ms** (job created + SSE connected) |
| HTTP connection held | Full scan duration | **~50ms** (job creation) |
| Dashboard usable during scan | Degraded (blocked event loop) | **Yes** (background worker + thread pool) |

---

## Observability Overhead Reduction

| Change | Impact |
|--------|--------|
| Removed per-tool-call OTEL child spans | Fewer spans exported per scenario |
| Tool call metadata on parent span | Debugging info preserved |
| Local trace cache prioritized | Avoids Phoenix dataframe fetch during scans |
| Single OTEL flush at scan end | Unchanged; appropriate for batch export |
| Blocking Phoenix queries moved to thread pool | No event loop blocking |

---

## Configuration Reference

```env
SCAN_CONCURRENCY=4              # Parallel scenarios (tune 2–8)
DIALOGFLOW_TIMEOUT_SECONDS=45
GEMINI_TIMEOUT_SECONDS=30
PHOENIX_EVAL_BATCH_SIZE=5
EVAL_CACHE_TTL_SECONDS=7200
REDIS_URL=redis://...           # Optional multi-instance cache
```

---

## Verification Checklist

- [ ] Run scan with default 26 scenarios; confirm parallel progress in agent checklist
- [ ] Confirm `POST /tools/scans` returns `job_id` in <500ms
- [ ] Confirm SSE events arrive before scan completes
- [ ] Re-run identical scan; verify eval cache hits in logs (`source: cache`)
- [ ] Dashboard polling pauses during scan (no duplicate fetches)
- [ ] Cloud Run deploy with `deploy/cloudrun-service.yaml`
- [ ] Monitor Phoenix span volume — should be ~26 spans/scan vs ~78+ before

---

## Files Changed

**New:** `tools/scan_engine.py`, `tools/job_queue.py`, `tools/cache.py`, `tools/http_clients.py`, `tools/scenario_loader.py`, `deploy/cloudrun-service.yaml`

**Modified:** `api/routes.py`, `api/main.py`, `tools/dialogflow_client.py`, `tools/eval_tools.py`, `tools/phoenix_tools.py`, `tools/db.py`, `tools/scenario_generator.py`, `agent/agent.py`, `dashboard/app.js`, `dashboard/index.html`, `dashboard/style.css`, `Dockerfile`, `.env.example`
