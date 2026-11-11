"""One-time read-only export of legacy SQLite history to ordinary documents."""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from config import HISTORY_DIR, LEGACY_DB_PATH, CrawlRecord
from storage import load_records, save_history, validate_records


def migrate_history(source: Path, history_dir: Path | None = None) -> int:
    """Preserve every row; never replace a conflicting, already migrated day."""
    import sqlite3

    if not source.is_file():
        raise FileNotFoundError(source)
    root = HISTORY_DIR if history_dir is None else history_dir
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        raw = [
            dict(row)
            for row in conn.execute(
                "SELECT date, keyword, item_count, seller_count, avg_price FROM crawl_records"
            )
        ]
    records = validate_records(raw)
    grouped: dict[str, list[CrawlRecord]] = defaultdict(list)
    for record in records:
        grouped[record["date"]].append(record)
    for day, rows in grouped.items():
        if (root / f"{day}.json").exists() and load_records(day, 1, history_dir=root) != rows:
            raise ValueError(f"历史文档 {day} 已有不同记录，停止导出以保护现有数据。")
    for rows in grouped.values():
        save_history(rows, history_dir=root)
    for day, rows in grouped.items():
        if load_records(day, 1, history_dir=root) != rows:
            raise ValueError(f"历史数据导出校验失败：{day}")
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将旧版数据库导出为 JSON 和中文 TXT 文档。")
    parser.add_argument("--source", type=Path, default=LEGACY_DB_PATH)
    args = parser.parse_args()
    print(f"已导出并核对 {migrate_history(args.source)} 条历史记录，文档目录：{HISTORY_DIR}")
