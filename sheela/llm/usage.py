"""Per-LLM-call usage logging.

Appends one JSON object per line to {log_dir}/api-usage.jsonl. Rotation is
handled externally (the Phase 1 weekly logrotate cron).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class UsageLogger:
    def __init__(self, log_dir: Path, filename: str = "api-usage.jsonl") -> None:
        self.log_path = log_dir / filename

    async def log(self, **fields: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        await asyncio.to_thread(self._append, entry)

    def _append(self, entry: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
