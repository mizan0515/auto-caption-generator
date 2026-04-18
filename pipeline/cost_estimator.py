"""Claude API 비용 추정기.

입력:
- pipeline.log 에 기록된 `Claude usage` 라인들 (claude_cli.py 의 A1 기능).
  형식: `Claude usage input_tokens=N output_tokens=N cache_creation_input_tokens=N
         cache_read_input_tokens=N session_id=... total_cost_usd=F`

산출:
- 실측: total_cost_usd 합산 (실제 호출된 모델 기준)
- 투영: 동일 token workload 를 각 모델(haiku/sonnet/opus)에 적용했을 때의 예상 비용

가격표 (USD per 1M tokens, 2025-11 기준):
- haiku  (Claude Haiku 4.5):  in=$1.00   out=$5.00
- sonnet (Claude Sonnet 4.5): in=$3.00   out=$15.00
- opus   (Claude Opus 4.1):   in=$15.00  out=$75.00

캐시 가격 규칙 (Anthropic 공식):
- cache_write = input_price * 1.25
- cache_read  = input_price * 0.10

가격 drift 가능성 있으므로 UI 에 "참고 수치" 명시. 실측 total_cost_usd 는
Claude CLI 가 제공하는 값을 그대로 사용 (가장 정확).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# USD per 1,000,000 tokens
PRICING: dict[str, dict[str, float]] = {
    "haiku": {"input": 1.00, "output": 5.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}

_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10

# 로그 포맷 변화 수용:
#   - legacy (Claude CLI subprocess 시대): "Claude usage input_tokens=... total_cost_usd=..."
#   - 현재 SDK:                              "Claude API usage (model) input_tokens=..."
#   - 현재 CLI fallback:                     "Claude CLI usage input_tokens=..."
# 공통: "Claude[ API|CLI]? usage ( optional (model) ) input_tokens=..."
# `(?:API\s+|CLI\s+)?` + optional `\([^)]*\)\s*` 로 세 형태 모두 매칭.
_USAGE_RE = re.compile(
    r"Claude\s+(?:API\s+|CLI\s+)?usage\s+"
    r"(?:\([^)]*\)\s+)?"
    r"input_tokens=(?P<input>\d+)\s+"
    r"output_tokens=(?P<output>\d+)\s+"
    r"cache_creation_input_tokens=(?P<cache_write>\d+)\s+"
    r"cache_read_input_tokens=(?P<cache_read>\d+)"
    r"(?:\s+session_id=\S+)?"
    r"(?:\s+total_cost_usd=(?P<cost>[0-9.]+))?"
)


@dataclass
class UsageCall:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    actual_cost_usd: float  # CLI 보고값 (0 이면 미기록)


@dataclass
class UsageStats:
    calls: int
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    actual_cost_usd: float

    @property
    def avg_input_per_call(self) -> float:
        return self.input_tokens / self.calls if self.calls else 0.0

    @property
    def avg_output_per_call(self) -> float:
        return self.output_tokens / self.calls if self.calls else 0.0

    @property
    def avg_cache_write_per_call(self) -> float:
        return self.cache_write_tokens / self.calls if self.calls else 0.0

    @property
    def avg_cache_read_per_call(self) -> float:
        return self.cache_read_tokens / self.calls if self.calls else 0.0


def parse_log_file(log_path: Path, max_calls: int | None = None) -> list[UsageCall]:
    """로그 파일에서 Claude usage 라인들을 파싱. 최신 max_calls 개만 반환."""
    if not log_path.exists():
        return []
    calls: list[UsageCall] = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _USAGE_RE.search(line)
                if not m:
                    continue
                calls.append(
                    UsageCall(
                        input_tokens=int(m.group("input")),
                        output_tokens=int(m.group("output")),
                        cache_write_tokens=int(m.group("cache_write")),
                        cache_read_tokens=int(m.group("cache_read")),
                        actual_cost_usd=float(m.group("cost") or 0.0),
                    )
                )
    except OSError:
        return []
    if max_calls and len(calls) > max_calls:
        calls = calls[-max_calls:]
    return calls


def aggregate(calls: list[UsageCall]) -> UsageStats:
    if not calls:
        return UsageStats(0, 0, 0, 0, 0, 0.0)
    return UsageStats(
        calls=len(calls),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        cache_write_tokens=sum(c.cache_write_tokens for c in calls),
        cache_read_tokens=sum(c.cache_read_tokens for c in calls),
        actual_cost_usd=sum(c.actual_cost_usd for c in calls),
    )


def estimate_cost(stats: UsageStats, model: str) -> float:
    """주어진 토큰 workload 를 model 에 적용했을 때 예상 비용 (USD).

    cache_write/read 는 input 기반 배수로 계산 (Anthropic 공식 규칙).
    """
    if model not in PRICING:
        return 0.0
    p = PRICING[model]
    ip = p["input"] / 1_000_000
    op = p["output"] / 1_000_000
    cost = (
        stats.input_tokens * ip
        + stats.output_tokens * op
        + stats.cache_write_tokens * ip * _CACHE_WRITE_MULT
        + stats.cache_read_tokens * ip * _CACHE_READ_MULT
    )
    return cost


def estimate_per_call(stats: UsageStats, model: str) -> float:
    """호출 1회 평균 예상 비용 (USD)."""
    if stats.calls == 0:
        return 0.0
    return estimate_cost(stats, model) / stats.calls


def format_usd(value: float) -> str:
    if value < 0.01:
        return f"${value*100:.2f}¢"  # 1센트 미만은 센트로
    if value < 1:
        return f"${value:.4f}"
    return f"${value:.2f}"


def format_tokens(n: float) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{int(n)}"
