"""파이프라인 공통 데이터 클래스"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VODInfo:
    video_no: str
    title: str
    channel_id: str
    channel_name: str
    duration: int  # 초
    publish_date: str
    thumbnail_url: str = ""
    category: str = ""
    streamer_id: str = ""  # "channel-{hex}" 또는 "name-{slug}". 빈 문자열이면 런타임에 derive.


@dataclass
class HighlightSegment:
    sec: float
    count: int
    raw_score: float
    composite: float
    z_count: float = 0.0
    z_score: float = 0.0
    rank: int = 0


@dataclass
class CommunityPost:
    title: str
    url: str
    body_preview: str = ""
    author: str = ""
    timestamp: str = ""
    views: int = 0
    comments: int = 0


@dataclass
class PipelineResult:
    video_no: str
    vod_info: Optional[VODInfo] = None
    video_path: Optional[str] = None
    srt_path: Optional[str] = None
    chat_log_path: Optional[str] = None
    highlights: list = field(default_factory=list)
    community_posts: list = field(default_factory=list)
    summary_md_path: Optional[str] = None
    summary_html_path: Optional[str] = None
    metadata_path: Optional[str] = None
    stage: str = "init"  # 현재 진행 단계
    error: Optional[str] = None
