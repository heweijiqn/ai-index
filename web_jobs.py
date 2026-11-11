"""Persistent, single-writer background jobs for the local web workbench."""

from __future__ import annotations

import copy
import json
import logging
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import LOCAL_TIMEZONE, OUTPUT_DIR, WEB_JOBS_DIR, CrawlProgress
from run_daily import run
from storage import _atomic_write

logger = logging.getLogger(__name__)


class JobConflict(ValueError):
    """The dedicated crawl profile already has an active web job."""


def parse_request(value: Any) -> tuple[list[str], int, str]:
    """Validate the complete request before creating a job or launching a browser."""
    if not isinstance(value, dict):
        raise TypeError("请求必须为 JSON 对象。")
    keywords = value.get("keywords")
    if (
        not isinstance(keywords, list)
        or not keywords
        or any(not isinstance(word, str) or not word.strip() for word in keywords)
    ):
        raise ValueError("请至少输入一个非空关键词。")
    limit = value.get("limit")
    if type(limit) is not int or limit <= 0:
        raise ValueError("每个关键词的抓取数量必须为正整数。")
    target = value.get("date")
    try:
        if not isinstance(target, str) or date.fromisoformat(target).isoformat() != target:
            raise ValueError
    except ValueError:
        raise ValueError("记录日期必须为 YYYY-MM-DD。") from None
    return list(dict.fromkeys(word.strip() for word in keywords)), limit, target


def now_str() -> str:
    """Use Beijing timestamps for job history, independent of record dates."""
    return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def job_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Exclude potentially large item previews from history lists."""
    fields = (
        "id",
        "created_at",
        "updated_at",
        "status",
        "stage",
        "keywords",
        "limit",
        "date",
        "error",
        "output_id",
    )
    result = {key: copy.deepcopy(job.get(key)) for key in fields}
    result.update(
        kind="job",
        total_items=sum(record["item_count"] for record in job.get("records", {}).values()),
    )
    return result


class JobManager:
    """Serialize requests and keep structured progress across browser refresh/restart."""

    def __init__(
        self,
        root: Path = WEB_JOBS_DIR,
        output_root: Path = OUTPUT_DIR,
        runner: Callable[..., Path] = run,
    ) -> None:
        self.root = root
        self.output_root = output_root
        self.runner = runner
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_id: str | None = None
        root.mkdir(parents=True, exist_ok=True)
        for path in root.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(job, dict) or job.get("id") != path.stem:
                    raise ValueError("任务 ID 与文件名不一致")
                if job["status"] in ("queued", "running"):
                    job.update(
                        status="interrupted",
                        stage="interrupted",
                        updated_at=now_str(),
                        error="上次服务已关闭，任务中断。可重新发起抓取。",
                    )
                    self._save(job)
                self.jobs[job["id"]] = job
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"任务记录损坏：{path.name}") from exc

    def _save(self, job: dict[str, Any]) -> None:
        _atomic_write(
            self.root / f"{job['id']}.json",
            json.dumps(job, ensure_ascii=False, allow_nan=False),
        )

    def start(self, value: Any) -> dict[str, Any]:
        """Reserve the single worker slot and return immediately for UI polling."""
        keywords, limit, target = parse_request(value)
        with self.lock:
            if self.active_id is not None:
                raise JobConflict("已有抓取任务运行中，请等待完成。")
            job: dict[str, Any] = {
                "id": uuid4().hex,
                "created_at": now_str(),
                "updated_at": now_str(),
                "keywords": keywords,
                "limit": limit,
                "date": target,
                "status": "queued",
                "stage": "queued",
                "keyword": "",
                "page": 0,
                "message": "任务已提交",
                "records": {},
                "items": {},
                "error": None,
                "output_id": None,
            }
            self._save(job)
            self.jobs[job["id"]] = job
            self.active_id = job["id"]
            thread = threading.Thread(target=self._execute, args=(job["id"],), daemon=True)
            thread.start()
            return copy.deepcopy(job)

    def _progress(self, job_id: str, event: CrawlProgress) -> None:
        with self.lock:
            job = self.jobs[job_id]
            for key in ("stage", "keyword", "page", "message", "output_id"):
                if key in event:
                    job[key] = event.get(key)
            if "record" in event:
                job["records"][event["record"]["keyword"]] = event["record"]
            if "items" in event and "keyword" in event:
                job["items"][event["keyword"]] = event["items"]
            job["updated_at"] = now_str()
            self._save(job)

    def _execute(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.update(status="running", stage="crawling", updated_at=now_str())
        try:
            with self.lock:
                self._save(job)
            folder = self.runner(
                job["date"],
                keywords=job["keywords"],
                limit=job["limit"],
                progress=lambda event: self._progress(job_id, event),
            )
            relative = folder.resolve().relative_to(self.output_root.resolve())
            if len(relative.parts) != 1:
                raise ValueError("本次结果目录无效。")
            with self.lock:
                job.update(
                    status="succeeded",
                    stage="completed",
                    output_id=relative.name,
                    message="抓取和图片生成已完成",
                )
        except Exception as exc:
            logger.exception("Web job failed: %s", job_id)
            with self.lock:
                job.update(status="failed", stage="failed", error=str(exc), message="本次任务失败")
        finally:
            with self.lock:
                job["updated_at"] = now_str()
                try:
                    self._save(job)
                except OSError:
                    logger.exception("Could not persist final job status")
                self.active_id = None

    def detail(self, job_id: str) -> dict[str, Any]:
        """Return an isolated view while the worker may be changing progress."""
        with self.lock:
            if job_id not in self.jobs:
                raise FileNotFoundError("找不到这次任务。")
            return copy.deepcopy(self.jobs[job_id])

    def summaries(self) -> list[dict[str, Any]]:
        """List requests including failed attempts without returning all item data."""
        with self.lock:
            return [job_summary(job) for job in self.jobs.values()]

    def active(self) -> dict[str, Any] | None:
        """Recover the running job after a page refresh or opening another tab."""
        with self.lock:
            return self.detail(self.active_id) if self.active_id is not None else None
