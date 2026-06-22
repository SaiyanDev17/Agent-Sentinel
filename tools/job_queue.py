"""
Background scan job queue with SSE-compatible event broadcasting.

Flow:
  POST /tools/scans  -> job_id (immediate)
  GET  /tools/scans/{id}/events -> SSE stream
  Worker processes scan asynchronously
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Callable, Awaitable

logger = logging.getLogger("job_queue")

EventCallback = Callable[[dict], Awaitable[None] | None]


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScanJob:
    job_id: str
    params: dict
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    progress: dict = field(default_factory=dict)
    release_score: dict | None = None
    error: str | None = None
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    subscribers: int = 0
    _history: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "release_score": self.release_score,
            "error": self.error,
        }


class JobQueue:
    """In-process job queue. Swap storage backend via REDIS_URL for multi-instance."""

    def __init__(self, max_jobs: int = 100):
        self._jobs: dict[str, ScanJob] = {}
        self._max_jobs = max_jobs
        self._worker_task: asyncio.Task | None = None
        self._pending: asyncio.Queue[str] = asyncio.Queue()
        self._scan_runner: Callable[[ScanJob, EventCallback], Awaitable[None]] | None = None

    def set_scan_runner(
        self,
        runner: Callable[[ScanJob, EventCallback], Awaitable[None]],
    ) -> None:
        self._scan_runner = runner

    async def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Scan job worker started")

    async def stop_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def create_job(self, params: dict) -> ScanJob:
        self._evict_old_jobs()
        job_id = f"scan_{uuid.uuid4().hex[:12]}"
        job = ScanJob(job_id=job_id, params=params)
        self._jobs[job_id] = job
        await self._pending.put(job_id)
        logger.info("Created scan job %s", job_id)
        return job

    def get_job(self, job_id: str) -> ScanJob | None:
        return self._jobs.get(job_id)

    async def publish_event(self, job: ScanJob, event: dict) -> None:
        job.updated_at = datetime.now(timezone.utc).isoformat()
        job._history.append(event)
        if event.get("status") == "processing":
            job.progress = {
                "index": event.get("index", 0),
                "total": event.get("total", 0),
                "scenario_id": event.get("scenario_id"),
                "agent": event.get("agent"),
                "message": event.get("message"),
                "agents_completed": event.get("agents_completed", job.progress.get("agents_completed", [])),
            }
        await job.events.put(event)

    async def subscribe_events(self, job_id: str) -> AsyncIterator[dict]:
        job = self.get_job(job_id)
        if not job:
            return
        job.subscribers += 1
        try:
            for past in job._history:
                yield past
            while True:
                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    if job.events.empty():
                        break
                try:
                    event = await asyncio.wait_for(job.events.get(), timeout=30.0)
                    yield event
                    if event.get("status") in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield {"status": "heartbeat", "job_id": job_id}
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                        break
        finally:
            job.subscribers -= 1

    def _evict_old_jobs(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        finished = [
            (jid, j)
            for jid, j in self._jobs.items()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        finished.sort(key=lambda x: x[1].updated_at)
        for jid, _ in finished[: max(1, len(self._jobs) - self._max_jobs + 1)]:
            self._jobs.pop(jid, None)

    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._pending.get()
            job = self._jobs.get(job_id)
            if not job or not self._scan_runner:
                continue
            job.status = JobStatus.RUNNING
            job.updated_at = datetime.now(timezone.utc).isoformat()

            async def emit(event: dict) -> None:
                await self.publish_event(job, event)

            try:
                await self._scan_runner(job, emit)
                if job.status == JobStatus.RUNNING:
                    job.status = JobStatus.COMPLETED
            except Exception as exc:
                logger.exception("Scan job %s failed", job_id)
                job.status = JobStatus.FAILED
                job.error = str(exc)
                await emit({"status": "error", "message": str(exc)})
            finally:
                job.updated_at = datetime.now(timezone.utc).isoformat()
                self._pending.task_done()


# Global singleton used by FastAPI routes
job_queue = JobQueue()
