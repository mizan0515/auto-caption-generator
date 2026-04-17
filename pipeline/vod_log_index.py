"""pipeline.log 를 VOD 경계 기준으로 스캔해 호출 토큰을 각 VOD 에 귀속시킨다.

핵심 규칙:
- 라인 `VOD 처리 시작: [<video_no>] <title>` 를 만나면 새 버킷 시작.
- 같은 버킷이 활성화된 동안 뒤따르는 `Claude usage ...` 호출을 모두 attribute.
- 다음 `VOD 처리 시작` 또는 EOF 에서 버킷 종료.

한계 (known):
- log rotation 으로 경계가 파일 밖으로 밀려난 호출은 "unknown VOD" 버킷에 들어간다.
- 한 VOD 가 여러 번 처리되면 (재시도 포함) 가장 최근 버킷만 UI 에 보여지는 게 아니라
  각 실행이 별도 entry 로 쌓인다. first-fit 이 아닌 "모든 실행" 보기.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.cost_estimator import UsageCall, _USAGE_RE  # type: ignore[attr-defined]

_VOD_START_RE = re.compile(r"VOD 처리 시작:\s*\[(?P<video_no>[^\]]+)\]\s*(?P<title>.*)")
_TIMESTAMP_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})")


@dataclass
class VODLogEntry:
    video_no: str
    title: str
    started_at: str  # ISO-ish, 첫 라인 타임스탬프
    calls: list[UsageCall] = field(default_factory=list)

    @property
    def total_input(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_cache_write(self) -> int:
        return sum(c.cache_write_tokens for c in self.calls)

    @property
    def total_cache_read(self) -> int:
        return sum(c.cache_read_tokens for c in self.calls)

    @property
    def actual_cost_usd(self) -> float:
        return sum(c.actual_cost_usd for c in self.calls)


def index_vods_from_log(log_path: Path) -> list[VODLogEntry]:
    """로그를 순차 스캔해 VOD 단위 entry 리스트 반환."""
    if not log_path.exists():
        return []

    entries: list[VODLogEntry] = []
    current: VODLogEntry | None = None
    # 경계 전에 나온 Claude usage 를 담을 sentinel
    orphan_bucket: VODLogEntry | None = None

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m_start = _VOD_START_RE.search(line)
                if m_start:
                    ts = _extract_ts(line)
                    current = VODLogEntry(
                        video_no=m_start.group("video_no").strip(),
                        title=m_start.group("title").strip(),
                        started_at=ts,
                    )
                    entries.append(current)
                    continue

                m_usage = _USAGE_RE.search(line)
                if m_usage:
                    call = UsageCall(
                        input_tokens=int(m_usage.group("input")),
                        output_tokens=int(m_usage.group("output")),
                        cache_write_tokens=int(m_usage.group("cache_write")),
                        cache_read_tokens=int(m_usage.group("cache_read")),
                        actual_cost_usd=float(m_usage.group("cost") or 0.0),
                    )
                    if current is not None:
                        current.calls.append(call)
                    else:
                        if orphan_bucket is None:
                            orphan_bucket = VODLogEntry(
                                video_no="(unknown)",
                                title="로그 회전 이전 호출 — VOD 경계 미식별",
                                started_at="",
                            )
                        orphan_bucket.calls.append(call)
    except OSError:
        return entries

    # orphan 은 첫 entry 앞에 둠 (시간순이 아니라 "unknown" 은 위로)
    if orphan_bucket is not None and orphan_bucket.calls:
        entries.insert(0, orphan_bucket)
    return entries


def _extract_ts(line: str) -> str:
    m = _TIMESTAMP_RE.search(line)
    return m.group("ts") if m else ""
