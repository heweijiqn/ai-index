"""Read-only history filters and safe artifact access for the web workbench."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import (
    HISTORY_DIR,
    LOCAL_TIMEZONE,
    OUTPUT_DIR,
    RECORDS_JSON_NAME,
    RECORDS_TEXT_NAME,
)
from storage import _read_document, validate_records
from web_jobs import JobManager


def date_filters(start: str, end: str) -> None:
    """Reject invalid/reversed date windows instead of returning misleading emptiness."""
    try:
        for value in (start, end):
            if value and date.fromisoformat(value).isoformat() != value:
                raise ValueError
    except ValueError:
        raise ValueError("筛选日期必须为 YYYY-MM-DD。") from None
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期。")


def matches(day: str, keywords: list[str], keyword: str, start: str, end: str) -> bool:
    return (
        (not start or day >= start)
        and (not end or day <= end)
        and (not keyword or any(keyword.casefold() in word.casefold() for word in keywords))
    )


def paginate(rows: list[dict[str, Any]], page: int, page_size: int = 20) -> dict[str, Any]:
    if page < 1:
        raise ValueError("页码必须大于 0。")
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = min(page, pages)
    return {
        "rows": rows[(page - 1) * page_size : page * page_size],
        "total": len(rows),
        "page": page,
        "pages": pages,
    }


def daily_history(
    keyword: str = "",
    start: str = "",
    end: str = "",
    page: int = 1,
    root: Path = HISTORY_DIR,
) -> dict[str, Any]:
    """Filter latest daily observations by record date and partial keyword."""
    date_filters(start, end)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), reverse=True):
        if (start and path.stem < start) or (end and path.stem > end):
            continue
        rows.extend(
            dict(row)
            for row in _read_document(path)
            if matches(row["date"], [row["keyword"]], keyword, start, end)
        )
    result = paginate(rows, page)
    result["summary"] = {
        "records": len(rows),
        "keywords": len({row["keyword"] for row in rows}),
        "days": len({row["date"] for row in rows}),
        "items": sum(row["item_count"] for row in rows),
    }
    return result


def output_folder(output_id: str, root: Path = OUTPUT_DIR) -> Path:
    """Allow one existing run directory, never arbitrary paths or escaping symlinks."""
    if not output_id or output_id in (".", "..") or "/" in output_id or "\\" in output_id:
        raise FileNotFoundError("结果目录无效。")
    folder = (root / output_id).resolve()
    if folder.parent != root.resolve() or not folder.is_dir():
        raise FileNotFoundError("找不到结果目录。")
    return folder


def snapshot(output_id: str, root: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Read existing CLI or web run snapshots without importing local credentials."""
    folder = output_folder(output_id, root)
    path = folder / RECORDS_JSON_NAME
    if path.resolve().parent != folder:
        raise FileNotFoundError("结果文档路径无效。")
    records = validate_records(json.loads(path.read_text(encoding="utf-8-sig")))
    if not records or len({row["date"] for row in records}) != 1:
        raise ValueError(f"运行快照损坏：{output_id}")
    suffix = records[0]["date"].replace("-", "_")
    names = [
        RECORDS_JSON_NAME,
        RECORDS_TEXT_NAME,
        "post.txt",
        f"card1_index_{suffix}.png",
        f"card2_daily_{suffix}.png",
        f"card3_weekly_{suffix}.png",
    ]
    files = [
        name
        for name in names
        if (folder / name).is_file() and (folder / name).resolve().parent == folder
    ]
    return {
        "id": output_id,
        "kind": "snapshot",
        "output_id": output_id,
        "created_at": datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TIMEZONE).isoformat(),
        "date": records[0]["date"],
        "keywords": [row["keyword"] for row in records],
        "total_items": sum(row["item_count"] for row in records),
        "limit": None,
        "status": "succeeded" if len(files) == len(names) else "incomplete",
        "records": records,
        "files": files,
    }


def artifact(output_id: str, name: str, root: Path = OUTPUT_DIR) -> Path:
    info = snapshot(output_id, root)
    if name not in info["files"]:
        raise FileNotFoundError("找不到该结果文件。")
    return output_folder(output_id, root) / name


def run_history(
    manager: JobManager,
    keyword: str = "",
    start: str = "",
    end: str = "",
    page: int = 1,
) -> dict[str, Any]:
    """Merge persistent web attempts and old output folders without duplicate runs."""
    date_filters(start, end)
    jobs = manager.summaries()
    linked = {job["output_id"] for job in jobs if job["output_id"]}
    rows = list(jobs)
    for path in manager.output_root.glob(f"*/{RECORDS_JSON_NAME}"):
        if path.parent.name not in linked:
            item = snapshot(path.parent.name, manager.output_root)
            item.pop("records")
            item.pop("files")
            rows.append(item)
    rows = [
        row for row in rows if matches(row["created_at"][:10], row["keywords"], keyword, start, end)
    ]
    rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
    return paginate(rows, page)
