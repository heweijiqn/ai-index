"""Document history, one-time migration and per-run isolation regressions."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import config
import migrate_history
import run_daily
import storage
from config import APP_TITLE, CrawlProgress, CrawlRecord


def row(day: str = "2026-11-11", keyword: str = "AI 副业", count: int = 10) -> CrawlRecord:
    return CrawlRecord(
        date=day, keyword=keyword, item_count=count, seller_count=min(5, count), avg_price=2.5
    )


def test_same_date_replaces_latest_but_preserves_run_documents(tmp_path: Path):
    history = tmp_path / "history"
    first = tmp_path / "run1"
    second = tmp_path / "run2"
    storage.save_records([row()], first, history_dir=history)
    original = {p.name: p.read_bytes() for p in first.iterdir()}
    storage.save_records([row(count=25)], second, history_dir=history)
    assert storage.load_records("2026-11-11", 1, history_dir=history) == [row(count=25)]
    assert {p.name: p.read_bytes() for p in first.iterdir()} == original
    text = (second / config.RECORDS_TEXT_NAME).read_text(encoding="utf-8-sig")
    assert text.startswith(APP_TITLE)
    assert "商品数量：25 件" in text
    assert "AI 副业" in text


def test_partial_keyword_update_retains_other_keywords(tmp_path: Path):
    storage.save_history([row(), row(keyword="Sora 教程")], history_dir=tmp_path)
    storage.save_history([row(count=25)], history_dir=tmp_path)
    rows = storage.load_records("2026-11-11", 1, history_dir=tmp_path)
    assert {(r["keyword"], r["item_count"]) for r in rows} == {("AI 副业", 25), ("Sora 教程", 10)}


def test_history_window_ignores_future_and_outside_dates(tmp_path: Path):
    for day in ("2026-11-01", "2026-11-10", "2026-11-11", "2026-11-12"):
        storage.save_history([row(day)], history_dir=tmp_path)
    assert [r["date"] for r in storage.load_records("2026-11-11", 2, history_dir=tmp_path)] == [
        "2026-11-10",
        "2026-11-11",
    ]


@pytest.mark.parametrize(
    "bad",
    [
        [{**row(), "item_count": -1}],
        [{**row(), "avg_price": float("nan")}],
        [{**row(), "date": "../invalid"}],
        [row(), row()],
    ],
)
def test_invalid_batch_cannot_change_existing_history(tmp_path: Path, bad):
    storage.save_history([row()], history_dir=tmp_path)
    original = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        storage.save_records(bad, tmp_path / "run", history_dir=tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == original


def test_corrupt_history_is_not_silently_skipped_or_overwritten(tmp_path: Path):
    (tmp_path / "2026-11-11.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="历史文档损坏"):
        storage.load_records("2026-11-11", 1, history_dir=tmp_path)
    with pytest.raises(ValueError, match="历史文档损坏"):
        storage.save_records([row()], tmp_path / "run", history_dir=tmp_path)
    assert not (tmp_path / "run").exists()


def test_atomic_replace_failure_preserves_original_and_cleans_temporary(
    monkeypatch, tmp_path: Path
):
    path = tmp_path / "report.txt"
    path.write_text("original", encoding="utf-8")

    def fail_replace(*_):
        raise OSError("simulated disk error")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError):
        storage._atomic_write(path, "new")
    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_legacy_export_is_read_only_and_idempotent(tmp_path: Path):
    source = tmp_path / "legacy.db"
    expected = [row("2026-11-10", count=0), row()]
    with sqlite3.connect(source) as conn:
        conn.execute(
            "CREATE TABLE crawl_records (date TEXT, keyword TEXT, item_count INT, seller_count INT, avg_price REAL)"
        )
        conn.executemany(
            "INSERT INTO crawl_records VALUES (?,?,?,?,?)", [tuple(r.values()) for r in expected]
        )
    before = hashlib.sha256(source.read_bytes()).digest()
    history = tmp_path / "history"
    assert migrate_history.migrate_history(source, history) == 2
    assert migrate_history.migrate_history(source, history) == 2
    assert storage.load_records("2026-11-11", 2, history_dir=history) == expected
    assert "全部为 0" in (history / "2026-11-10.txt").read_text(encoding="utf-8-sig")
    assert hashlib.sha256(source.read_bytes()).digest() == before
    storage.save_history([row(count=15)], history_dir=history)
    with pytest.raises(ValueError, match="保护现有数据"):
        migrate_history.migrate_history(source, history)
    assert storage.load_records("2026-11-11", 1, history_dir=history) == [row(count=15)]


def test_two_daily_runs_have_separate_images_text_and_data(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "HISTORY_DIR", tmp_path / "data" / "history")
    monkeypatch.setattr(storage, "HISTORY_DIR", config.HISTORY_DIR)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    batches = iter([[row(count=10)], [row(count=20)]])

    def crawl(**kwargs):
        records = next(batches)
        if kwargs.get("progress"):
            kwargs["progress"]({"stage": "crawling", "record": records[0]})
        return records

    monkeypatch.setattr(run_daily, "crawl_all", crawl)
    run_daily.run("2026-11-11")
    first = next(config.OUTPUT_DIR.iterdir())
    original = {p.name: p.read_bytes() for p in first.iterdir()}
    events: list[CrawlProgress] = []
    second = run_daily.run("2026-11-11", progress=events.append)
    folders = list(config.OUTPUT_DIR.iterdir())
    assert second in folders
    assert [event["stage"] for event in events] == [
        "crawling",
        "crawling",
        "saving",
        "analyzing",
        "rendering",
    ]
    assert len(folders) == 2
    assert {p.name: p.read_bytes() for p in first.iterdir()} == original
    for folder in folders:
        assert len(list(folder.glob("*.png"))) == 3
        assert (folder / "post.txt").is_file()
        assert (folder / config.RECORDS_TEXT_NAME).is_file()
        records = json.loads((folder / config.RECORDS_JSON_NAME).read_text(encoding="utf-8-sig"))
        assert records[0]["item_count"] in (10, 20)
    assert storage.load_records("2026-11-11", 1)[0]["item_count"] == 20
    assert not (config.DATA_DIR / "index.db").exists()
