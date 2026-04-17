"""일별 비용 트렌드 집계.

pipeline.log 의 Claude usage 라인을 날짜별로 묶어 (date, calls, tokens, cost)
리스트를 돌려준다. 타임스탬프는 라인 선두의 `YYYY-MM-DD HH:MM:SS` 를 사용.

대시보드 Canvas 차트에서 최근 N 일을 막대그래프로 보여주기 위한 데이터 소스.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from pipeline.cost_estimator import _USAGE_RE  # type: ignore[attr-defined]

_DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})[T\s]")


@dataclass
class DailyCost:
    day: date
    calls: int
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    actual_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.cache_read_tokens
        )


def aggregate_by_day(log_path: Path, days: int = 14) -> list[DailyCost]:
    """최근 `days` 일의 일별 집계. 호출이 없는 날도 0 으로 채워 반환."""
    if not log_path.exists():
        return _fill_empty(days)

    buckets: dict[date, DailyCost] = {}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m_usage = _USAGE_RE.search(line)
                if not m_usage:
                    continue
                m_date = _DATE_RE.search(line)
                if not m_date:
                    continue
                try:
                    d = datetime.strptime(m_date.group("date"), "%Y-%m-%d").date()
                except ValueError:
                    continue
                entry = buckets.get(d)
                if entry is None:
                    entry = DailyCost(
                        day=d,
                        calls=0,
                        input_tokens=0,
                        output_tokens=0,
                        cache_write_tokens=0,
                        cache_read_tokens=0,
                        actual_cost_usd=0.0,
                    )
                    buckets[d] = entry
                entry.calls += 1
                entry.input_tokens += int(m_usage.group("input"))
                entry.output_tokens += int(m_usage.group("output"))
                entry.cache_write_tokens += int(m_usage.group("cache_write"))
                entry.cache_read_tokens += int(m_usage.group("cache_read"))
                entry.actual_cost_usd += float(m_usage.group("cost") or 0.0)
    except OSError:
        return _fill_empty(days)

    today = date.today()
    start = today - timedelta(days=days - 1)
    series: list[DailyCost] = []
    for i in range(days):
        d = start + timedelta(days=i)
        series.append(
            buckets.get(d)
            or DailyCost(
                day=d,
                calls=0,
                input_tokens=0,
                output_tokens=0,
                cache_write_tokens=0,
                cache_read_tokens=0,
                actual_cost_usd=0.0,
            )
        )
    return series


def _fill_empty(days: int) -> list[DailyCost]:
    today = date.today()
    start = today - timedelta(days=days - 1)
    return [
        DailyCost(
            day=start + timedelta(days=i),
            calls=0,
            input_tokens=0,
            output_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            actual_cost_usd=0.0,
        )
        for i in range(days)
    ]
