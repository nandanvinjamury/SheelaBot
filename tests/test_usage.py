import json
from pathlib import Path

from sheela.llm.usage import UsageLogger


async def test_writes_jsonl(tmp_path: Path):
    logger = UsageLogger(tmp_path)
    await logger.log(
        channel="#general",
        model="gemini-2.5-flash",
        input_tokens=100,
        output_tokens=50,
        latency_ms=1234,
    )
    log_file = tmp_path / "api-usage.jsonl"
    assert log_file.exists()
    entry = json.loads(log_file.read_text().strip())
    assert entry["channel"] == "#general"
    assert entry["model"] == "gemini-2.5-flash"
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 50
    assert entry["latency_ms"] == 1234
    assert "timestamp" in entry
    assert entry["timestamp"].endswith("+00:00")  # UTC


async def test_appends_multiple_entries(tmp_path: Path):
    logger = UsageLogger(tmp_path)
    await logger.log(model="m1", input_tokens=10, output_tokens=5, latency_ms=100)
    await logger.log(model="m2", input_tokens=20, output_tokens=10, latency_ms=200)
    lines = (tmp_path / "api-usage.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["model"] == "m1"
    assert json.loads(lines[1])["model"] == "m2"


async def test_creates_log_dir(tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c"
    logger = UsageLogger(nested)
    await logger.log(model="x", input_tokens=1, output_tokens=1, latency_ms=1)
    assert (nested / "api-usage.jsonl").exists()
