"""Ordinary JSON history documents and Chinese TXT reports; no database needed."""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from config import (
    APP_TITLE,
    HISTORY_DIR,
    LOCAL_TIMEZONE,
    RECORDS_JSON_NAME,
    RECORDS_TEXT_NAME,
    CrawlRecord,
    create_run_dir,
)


def validate_records(value: Any) -> list[CrawlRecord]:
    """Reject invalid batches before writing any document."""
    if not isinstance(value, list):
        raise TypeError("抓取记录必须是列表。")
    result: list[CrawlRecord] = []
    seen: set[tuple[str, str]] = set()
    for row in value:
        if not isinstance(row, dict):
            raise TypeError("抓取记录格式不正确。")
        day, keyword = row.get("date"), row.get("keyword")
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("记录日期必须为 YYYY-MM-DD。")
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("关键词不能为空。")
        count, sellers, price = row.get("item_count"), row.get("seller_count"), row.get("avg_price")
        if type(count) is not int or type(sellers) is not int or not 0 <= sellers <= count:
            raise ValueError("商品数和卖家数必须是有效的非负整数。")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise TypeError("平均价格必须是有效的非负数。")
        if not math.isfinite(price) or price < 0:
            raise ValueError("平均价格必须是有效的非负数。")
        if (day, keyword) in seen:
            raise ValueError(f"同一日期的关键词重复：{day} {keyword}")
        seen.add((day, keyword))
        result.append(
            CrawlRecord(
                date=day,
                keyword=keyword,
                item_count=count,
                seller_count=sellers,
                avg_price=float(price),
            )
        )
    return sorted(result, key=lambda row: (row["date"], row["keyword"]))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="\n",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_text(records: list[CrawlRecord]) -> str:
    return json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _read_document(path: Path) -> list[CrawlRecord]:
    try:
        records = validate_records(json.loads(path.read_text(encoding="utf-8-sig")))
        if any(record["date"] != path.stem for record in records):
            raise ValueError("记录日期与文件名不一致。")
        return records
    except (ValueError, TypeError) as exc:
        raise ValueError(f"历史文档损坏：{path.name}；{exc}") from exc


def records_text(records: list[CrawlRecord]) -> str:
    """Produce a plain Chinese document that opens directly in Windows Notepad."""
    lines = [
        f"{APP_TITLE} — 抓取数据",
        "=" * 48,
        "文档时间（北京时间）：" + datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
        f"关键词记录数：{len(records)}",
        f"商品记录合计：{sum(row['item_count'] for row in records)}",
        "说明：商品数量为本次搜索的去重采样数，关键词之间可能包含重复商品。",
        "",
    ]
    if records and not any(row["item_count"] for row in records):
        lines.extend(
            ["注意：本日记录全部为 0，可能包含旧版抓取失败的数据，不宜解读为真实市场数据。", ""]
        )
    for row in records:
        lines.extend(
            [
                f"日期：{row['date']}    关键词：{row['keyword']}",
                f"商品数量：{row['item_count']} 件    卖家数量：{row['seller_count']} 位",
                f"平均价格：{row['avg_price']:.2f} 元",
                "-" * 48,
            ]
        )
    return "\n".join(lines) + "\n"


def save_history(records: list[CrawlRecord], *, history_dir: Path | None = None) -> None:
    """Save documents without making a run folder, for an explicit legacy import."""
    checked = validate_records(records)
    if len({row["date"] for row in checked}) != 1:
        raise ValueError("一次保存必须包含且只能包含一个日期。")
    day = checked[0]["date"]
    root = HISTORY_DIR if history_dir is None else history_dir
    history_path = root / f"{day}.json"
    previous = _read_document(history_path) if history_path.exists() else []
    merged = {row["keyword"]: row for row in previous}
    merged.update({row["keyword"]: row for row in checked})
    latest = validate_records(list(merged.values()))
    _atomic_write(root / f"{day}.txt", records_text(latest))
    _atomic_write(history_path, _json_text(latest))


def save_records(
    records: list[CrawlRecord],
    output_dir: Path | None = None,
    *,
    history_dir: Path | None = None,
) -> Path:
    """Save latest daily history plus an immutable snapshot for this invocation."""
    checked = validate_records(records)
    days = {row["date"] for row in checked}
    if len(days) != 1:
        raise ValueError("一次保存必须包含且只能包含一个日期。")
    day = checked[0]["date"]
    root = HISTORY_DIR if history_dir is None else history_dir
    history_path = root / f"{day}.json"
    previous = _read_document(history_path) if history_path.exists() else []
    merged = {row["keyword"]: row for row in previous}
    merged.update({row["keyword"]: row for row in checked})
    latest = validate_records(list(merged.values()))
    run_dir = create_run_dir(day) if output_dir is None else output_dir
    # Save the run snapshot first; history commits only after its report is ready.
    _atomic_write(run_dir / RECORDS_TEXT_NAME, records_text(checked))
    _atomic_write(run_dir / RECORDS_JSON_NAME, _json_text(checked))
    _atomic_write(root / f"{day}.txt", records_text(latest))
    _atomic_write(history_path, _json_text(latest))
    return run_dir


def load_records(
    target_date: str,
    days: int,
    *,
    history_dir: Path | None = None,
) -> list[CrawlRecord]:
    """Read the latest snapshot for each date in the requested history window."""
    end = date.fromisoformat(target_date)
    if days < 1:
        raise ValueError("历史天数必须大于 0。")
    start = end - timedelta(days=days - 1)
    root = HISTORY_DIR if history_dir is None else history_dir
    result: list[CrawlRecord] = []
    for offset in range(days):
        path = root / f"{(start + timedelta(days=offset)).isoformat()}.json"
        if path.exists():
            result.extend(_read_document(path))
    return result
