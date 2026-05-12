"""Aggregate Sheela's api-usage.jsonl log.

Usage:
    python tools/analyze_usage.py [--log PATH] [--since YYYY-MM-DD | --days N]
                                  [--group-by channel hour model task ...]

Or, after `pip install -e .`:
    sheela-usage --days 7 --group-by channel model
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_LOG = Path("/home/sheela/logs/api-usage.jsonl")
GROUPS = ("channel", "hour", "model", "task")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Aggregate Sheela usage logs by channel/hour/model/task."
    )
    p.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help=f"Path to api-usage.jsonl (default {DEFAULT_LOG})",
    )
    p.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only entries from the last N days (UTC).",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only entries on/after YYYY-MM-DD (UTC).",
    )
    p.add_argument(
        "--group-by",
        nargs="+",
        choices=GROUPS,
        default=["channel", "model"],
        help="One or more groupings to print (default: channel model).",
    )
    return p.parse_args(argv)


def load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        print(f"log file not found: {path}", file=sys.stderr)
        sys.exit(1)
    entries: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def filter_since(
    entries: list[dict[str, Any]], since: datetime
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in entries:
        ts = e.get("timestamp")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        if ts_dt >= since:
            out.append(e)
    return out


def hour_key(entry: dict[str, Any]) -> str:
    ts = entry.get("timestamp")
    if not ts:
        return "?"
    try:
        ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return ts_dt.strftime("%Y-%m-%d %H:00")
    except ValueError:
        return "?"


KEY_FNS: dict[str, Callable[[dict[str, Any]], str]] = {
    "channel": lambda e: str(e.get("channel", "?")),
    "hour": hour_key,
    "model": lambda e: str(e.get("model", "?")),
    "task": lambda e: str(e.get("task", "?")),
}


def aggregate(
    entries: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
            "latency_ms_total": 0,
        }
    )
    for e in entries:
        k = key_fn(e)
        out[k]["calls"] += 1
        out[k]["input_tokens"] += int(e.get("input_tokens", 0) or 0)
        out[k]["output_tokens"] += int(e.get("output_tokens", 0) or 0)
        out[k]["cached_tokens"] += int(e.get("cached_tokens", 0) or 0)
        out[k]["latency_ms_total"] += int(e.get("latency_ms", 0) or 0)
    for v in out.values():
        v["avg_latency_ms"] = (
            round(v["latency_ms_total"] / v["calls"]) if v["calls"] else 0
        )
    return dict(out)


def print_table(title: str, agg: dict[str, dict[str, Any]]) -> None:
    if not agg:
        return
    print()
    print(f"=== by {title} ===")
    cols = (
        "calls",
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "avg_latency_ms",
    )
    header = f"{title:<30} " + " ".join(f"{c:>15}" for c in cols)
    print(header)
    print("-" * len(header))
    items = sorted(agg.items(), key=lambda kv: kv[1]["calls"], reverse=True)
    totals = {c: 0 for c in cols if c != "avg_latency_ms"}
    total_latency_ms = 0
    total_calls = 0
    for key, v in items:
        row = f"{str(key):<30} " + " ".join(f"{v[c]:>15,}" for c in cols)
        print(row)
        for c in cols:
            if c == "avg_latency_ms":
                continue
            totals[c] += v[c]
        total_latency_ms += v["latency_ms_total"]
        total_calls += v["calls"]
    avg_lat = round(total_latency_ms / total_calls) if total_calls else 0
    print("-" * len(header))
    totals_with_lat = dict(totals)
    totals_with_lat["avg_latency_ms"] = avg_lat
    print(
        f"{'TOTAL':<30} "
        + " ".join(f"{totals_with_lat[c]:>15,}" for c in cols)
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    since: datetime | None = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            return 2
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    elif args.days is not None:
        since = datetime.now(tz=timezone.utc) - timedelta(days=args.days)

    entries = load_entries(args.log)
    if since:
        entries = filter_since(entries, since)

    if not entries:
        print("no entries to analyze")
        return 0

    print(f"Total entries: {len(entries)}")
    if since:
        print(f"Since: {since.isoformat()}")

    for grp in args.group_by:
        print_table(grp, aggregate(entries, KEY_FNS[grp]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
