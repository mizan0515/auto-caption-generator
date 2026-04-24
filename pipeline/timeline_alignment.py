from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from .utils import sec_to_hms


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


@dataclass
class TimeAnchor:
    src_sec: int
    dst_sec: int
    label: str = ""


@dataclass
class AlignmentProfile:
    source_platform: str
    target_platform: str
    mode: str
    anchors: list[TimeAnchor]
    confidence: float
    notes: str = ""


def hms_to_sec(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    parts = text.split(":")
    if len(parts) == 2:
        hh = 0
        mm, ss = parts
    elif len(parts) == 3:
        hh, mm, ss = parts
    else:
        raise ValueError(f"invalid timestamp: {value}")
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def extract_youtube_video_id(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        raise ValueError("unsupported YouTube URL")
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/")
    else:
        video_id = (parse_qs(parsed.query).get("v") or [""])[0].strip()
    if not re.fullmatch(r"[\w-]{11}", video_id):
        raise ValueError("invalid YouTube video id")
    return video_id


def fetch_youtube_video_info(url: str, timeout_sec: int = 15) -> dict[str, Any]:
    video_id = extract_youtube_video_id(url)
    oembed_url = "https://www.youtube.com/oembed?" + urlencode(
        {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}
    )
    title = ""
    channel = ""
    try:
        with urlopen(oembed_url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
            title = str(payload.get("title") or "").strip()
            channel = str(payload.get("author_name") or "").strip()
    except URLError as exc:
        raise RuntimeError(f"failed to fetch YouTube oEmbed: {exc}") from exc

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with urlopen(watch_url, timeout=timeout_sec) as response:
            html = response.read().decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(f"failed to fetch YouTube watch page: {exc}") from exc

    match = re.search(r'"lengthSeconds":"(?P<sec>\d+)"', html)
    if not match:
        raise RuntimeError("failed to parse YouTube duration")

    duration_sec = int(match.group("sec"))
    has_chapters = "chapters" in html
    return {
        "video_id": video_id,
        "title": title,
        "channel": channel,
        "duration_sec": duration_sec,
        "watch_url": watch_url,
        "has_chapters": has_chapters,
    }


def build_offset_profile(source_duration_sec: int, target_duration_sec: int) -> AlignmentProfile:
    offset_sec = int(source_duration_sec) - int(target_duration_sec)
    return AlignmentProfile(
        source_platform="chzzk",
        target_platform="youtube",
        mode="offset",
        anchors=[TimeAnchor(src_sec=0, dst_sec=-offset_sec, label="auto-duration-offset")],
        confidence=0.45,
        notes=f"source-target duration diff {offset_sec} sec",
    )


def build_profile_from_anchor_dicts(
    anchors: list[dict[str, Any]],
    fallback_offset_sec: int,
) -> AlignmentProfile:
    parsed: list[TimeAnchor] = []
    for row in anchors:
        src_tc = str(row.get("src_tc") or "").strip()
        dst_tc = str(row.get("dst_tc") or "").strip()
        if not src_tc or not dst_tc:
            continue
        parsed.append(
            TimeAnchor(
                src_sec=hms_to_sec(src_tc),
                dst_sec=hms_to_sec(dst_tc),
                label=str(row.get("label") or "").strip(),
            )
        )
    if not parsed:
        return AlignmentProfile(
            source_platform="chzzk",
            target_platform="youtube",
            mode="offset",
            anchors=[TimeAnchor(src_sec=0, dst_sec=-fallback_offset_sec, label="auto-duration-offset")],
            confidence=0.45,
            notes="duration-only auto alignment",
        )

    parsed.sort(key=lambda item: (item.src_sec, item.dst_sec))
    if len(parsed) == 1:
        anchor = parsed[0]
        return AlignmentProfile(
            source_platform="chzzk",
            target_platform="youtube",
            mode="offset",
            anchors=[TimeAnchor(src_sec=0, dst_sec=anchor.dst_sec - anchor.src_sec, label=anchor.label or "manual-anchor")],
            confidence=0.72,
            notes="single manual anchor",
        )

    offsets = [item.src_sec - item.dst_sec for item in parsed]
    spread = max(offsets) - min(offsets)
    if spread <= 5:
        avg_offset = round(sum(offsets) / len(offsets))
        return AlignmentProfile(
            source_platform="chzzk",
            target_platform="youtube",
            mode="offset",
            anchors=[TimeAnchor(src_sec=0, dst_sec=-avg_offset, label="manual-anchor-average")],
            confidence=0.86,
            notes=f"manual anchors agree within {spread} sec",
        )

    confidence = 0.78 if len(parsed) == 2 else 0.9
    return AlignmentProfile(
        source_platform="chzzk",
        target_platform="youtube",
        mode="piecewise",
        anchors=parsed,
        confidence=confidence,
        notes=f"piecewise profile from {len(parsed)} anchors",
    )


def map_sec(src_sec: int, profile: AlignmentProfile) -> int:
    value = max(0, int(src_sec))
    if not profile.anchors:
        return value
    if profile.mode == "offset":
        anchor = profile.anchors[0]
        return max(0, value + (anchor.dst_sec - anchor.src_sec))

    anchors = sorted(profile.anchors, key=lambda item: item.src_sec)
    if value <= anchors[0].src_sec:
        shift = anchors[0].dst_sec - anchors[0].src_sec
        return max(0, value + shift)
    if value >= anchors[-1].src_sec:
        shift = anchors[-1].dst_sec - anchors[-1].src_sec
        return max(0, value + shift)

    for left, right in zip(anchors, anchors[1:]):
        if left.src_sec <= value <= right.src_sec:
            span = right.src_sec - left.src_sec
            if span <= 0:
                return max(0, value + (left.dst_sec - left.src_sec))
            ratio = (value - left.src_sec) / span
            mapped = round(left.dst_sec + ratio * (right.dst_sec - left.dst_sec))
            return max(0, mapped)
    return value


def remap_sections(sec: dict[str, Any], profile: AlignmentProfile) -> dict[str, Any]:
    out = copy.deepcopy(sec)
    for item in out.get("timeline") or []:
        src_tc = item.get("tc") or ""
        try:
            src_sec = hms_to_sec(src_tc)
        except ValueError:
            continue
        dst_sec = map_sec(src_sec, profile)
        item["src_tc"] = src_tc
        item["tc"] = sec_to_hms(dst_sec)
    for item in out.get("highlights") or []:
        tc_range = str(item.get("tc_range") or "").strip()
        match = re.match(r"(?P<start>\d{2}:\d{2}:\d{2})\s*~\s*(?P<end>\d{2}:\d{2}:\d{2})", tc_range)
        if not match:
            continue
        start_sec = map_sec(hms_to_sec(match.group("start")), profile)
        end_sec = map_sec(hms_to_sec(match.group("end")), profile)
        item["src_tc_range"] = tc_range
        item["tc_range"] = f"{sec_to_hms(start_sec)}~{sec_to_hms(end_sec)}"
    return out


def pick_anchor_candidates(sec: dict[str, Any], limit: int = 4) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for item in sec.get("timeline") or []:
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not title or not item.get("tc"):
            continue
        candidates.append(
            {
                "src_tc": item["tc"],
                "label": title,
                "summary": summary[:160],
            }
        )
    interesting = [item for item in candidates if any(token in item["label"] for token in ("픽", "승리", "탄생", "확정", "개막", "커버"))]
    pool = interesting or candidates
    return pool[:limit]


def _strip_inline_md(value: str) -> str:
    text = str(value or "")
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def render_youtube_comment_text(
    remapped_sec: dict[str, Any],
    profile: AlignmentProfile,
    compact: bool = False,
) -> str:
    _ = compact, profile
    lines: list[str] = []
    for item in remapped_sec.get("timeline") or []:
        tc = str(item.get("tc") or "").strip()
        title = _strip_inline_md(item.get("title") or "").strip()
        if not tc or not title:
            continue
        mood_raw = str(item.get("mood_raw") or "").strip()
        if mood_raw:
            lines.append(f"[{tc}] {title} (분위기: {mood_raw})")
        else:
            lines.append(f"[{tc}] {title}")
    return "\n".join(lines)
