import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.analyze_usage import (
    aggregate,
    filter_since,
    hour_key,
    load_entries,
    main,
)


def _entry(**overrides):
    base = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "channel": "#general",
        "model": "gemini-2.5-flash",
        "task": "respond",
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_tokens": 0,
        "latency_ms": 200,
    }
    base.update(overrides)
    return base


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    p = tmp_path / "api-usage.jsonl"
    entries = [
        _entry(channel="#general", model="gemini-2.5-flash"),
        _entry(channel="#general", model="gemini-2.5-flash"),
        _entry(channel="#health", model="gemini-2.5-flash"),
        _entry(channel="#side-project", model="gemini-2.5-pro"),
        # Old entry (10 days ago)
        _entry(
            timestamp=(
                datetime.now(timezone.utc) - timedelta(days=10)
            ).isoformat(),
            channel="#general",
        ),
    ]
    p.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return p


def test_load_entries_skips_blank_and_malformed(tmp_path: Path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"a":1}\n\n{"not-json}\n{"b":2}\n', encoding="utf-8"
    )
    assert load_entries(p) == [{"a": 1}, {"b": 2}]


def test_load_entries_missing_file_exits(tmp_path: Path):
    with pytest.raises(SystemExit):
        load_entries(tmp_path / "nope.jsonl")


def test_aggregate_by_channel(log_file: Path):
    entries = load_entries(log_file)
    agg = aggregate(entries, lambda e: e["channel"])
    assert agg["#general"]["calls"] == 3
    assert agg["#general"]["input_tokens"] == 300
    assert agg["#general"]["output_tokens"] == 150
    assert agg["#general"]["avg_latency_ms"] == 200
    assert agg["#health"]["calls"] == 1
    assert agg["#side-project"]["calls"] == 1


def test_aggregate_by_model(log_file: Path):
    entries = load_entries(log_file)
    agg = aggregate(entries, lambda e: e["model"])
    assert agg["gemini-2.5-flash"]["calls"] == 4
    assert agg["gemini-2.5-pro"]["calls"] == 1


def test_hour_key():
    e = {"timestamp": "2026-05-12T14:35:22+00:00"}
    assert hour_key(e) == "2026-05-12 14:00"


def test_filter_since():
    now = datetime.now(timezone.utc)
    entries = [
        {"timestamp": (now - timedelta(days=15)).isoformat()},
        {"timestamp": (now - timedelta(days=3)).isoformat()},
        {"timestamp": now.isoformat()},
    ]
    filtered = filter_since(entries, now - timedelta(days=7))
    assert len(filtered) == 2


def test_filter_since_handles_missing_or_invalid_timestamps():
    now = datetime.now(timezone.utc)
    entries = [
        {"timestamp": "not-a-timestamp"},
        {},  # no timestamp at all
        {"timestamp": now.isoformat()},
    ]
    filtered = filter_since(entries, now - timedelta(days=1))
    assert len(filtered) == 1


def test_main_runs_and_prints(log_file: Path, capsys: pytest.CaptureFixture):
    rc = main(["--log", str(log_file), "--group-by", "channel", "model"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Total entries" in out
    assert "by channel" in out
    assert "by model" in out
    assert "#general" in out


def test_main_with_days_filter(log_file: Path, capsys: pytest.CaptureFixture):
    rc = main(["--log", str(log_file), "--days", "7", "--group-by", "channel"])
    assert rc == 0
    out = capsys.readouterr().out
    # The 10-day-old entry should be excluded; #general now has 2 instead of 3
    assert "Total entries: 4" in out


def test_main_with_no_entries(tmp_path: Path, capsys: pytest.CaptureFixture):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    rc = main(["--log", str(p)])
    assert rc == 0
    assert "no entries" in capsys.readouterr().out


def test_main_with_bad_since_format(log_file: Path, capsys: pytest.CaptureFixture):
    rc = main(["--log", str(log_file), "--since", "not-a-date"])
    assert rc == 2
