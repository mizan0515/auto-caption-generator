"""2단계 요약 오케스트레이션: 청크별 분석 → 통합 리포트"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .chat_analyzer import format_chat_highlights_for_prompt, get_chats_in_range
from .claude_cli import call_claude
from .models import VODInfo, CommunityPost
from .scraper import format_community_for_prompt
from .utils import sec_to_hms

logger = logging.getLogger("pipeline")

KST = timezone(timedelta(hours=9))

# 프롬프트 템플릿 경로
_MERGE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "청크 통합 프롬프트.md"


def _load_merge_prompt() -> str:
    if _MERGE_PROMPT_PATH.exists():
        with open(_MERGE_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    logger.warning(f"통합 프롬프트 파일 없음: {_MERGE_PROMPT_PATH}")
    return _default_merge_prompt()


def _default_merge_prompt() -> str:
    return """# Role: 전문 방송 모니터링가

아래는 chunk_01 ~ chunk_N의 결과이다.
{CHUNK_RESULTS_ALL}

# Tasks
1. 오버랩 구간 중복을 병합하라.
2. 시간순 정렬하라.
3. 최종 타임라인 항목은 20개 정도.

# Output Format
## 📋 방송 분석 리포트: [방송 제목]
- **핵심 요약:** (해쉬태그 3개)
> "한줄평"

### 📍 타임라인 상세 요약
- **[00:00:00] 세션명** (분위기: 🔥/💬/💤)
    - 내용: ...

### 🎬 하이라이트 추천 구간
1. **[타임코드]** 내용 설명

### 📝 에디터의 방송 후기
- (2~3문단)
"""


def _build_chunk_prompt(
    chunk: dict,
    highlights: list[dict],
    chats: list[dict],
    vod_info: VODInfo,
) -> str:
    """개별 청크 분석용 프롬프트 생성"""
    start_sec = chunk["start_ms"] / 1000
    end_sec = chunk["end_ms"] / 1000

    # 해당 시간대 하이라이트
    relevant_highlights = [
        h for h in highlights
        if start_sec - 30 <= h["sec"] <= end_sec + 30
    ]

    # 해당 시간대 채팅 하이라이트 포맷
    chat_section = ""
    if relevant_highlights and chats:
        chat_section = format_chat_highlights_for_prompt(relevant_highlights, chats, context_sec=20)

    prompt = f"""너는 한국 라이브 방송 분석 전문가야. 아래는 "{vod_info.title}" 방송의 일부 구간 ({chunk['start_hhmmss']} ~ {chunk['end_hhmmss']}) 자막과 채팅 데이터야.

## 채팅 하이라이트 (이 구간)
{chat_section if chat_section else "(채팅 데이터 없음)"}

## 자막 (Transcript)
{chunk['text']}

## 작업
이 구간의 타임라인 요약을 작성해줘:
1. 주요 순간을 시간순으로 정리 (각 항목에 타임코드, 내용, 분위기 포함)
2. 특히 재미있거나 의미있는 순간을 하이라이트로 표시
3. 채팅 반응이 뜨거웠던 순간을 강조
4. 간결하게, 핵심만 작성

포맷:
- **[HH:MM:SS] 세션명** (분위기: 🔥/💬/💤)
    - 내용: ...
    - 근거: (채팅 반응 등)
"""
    return prompt


def process_chunks(
    chunks: list[dict],
    highlights: list[dict],
    chats: list[dict],
    vod_info: VODInfo,
    claude_timeout: int = 300,
) -> list[str]:
    """각 청크를 독립적으로 Claude에 전달하여 분석"""
    chunk_results = []

    for chunk in chunks:
        prompt = _build_chunk_prompt(chunk, highlights, chats, vod_info)
        logger.info(
            f"  청크 {chunk['index']}/{len(chunks)} 분석 중 "
            f"({chunk['start_hhmmss']}~{chunk['end_hhmmss']}, {chunk['char_count']:,}자)..."
        )

        try:
            result = call_claude(prompt, timeout=claude_timeout)
            chunk_results.append(f"## chunk_{chunk['index']:02d} ({chunk['start_hhmmss']}~{chunk['end_hhmmss']})\n\n{result}")
            logger.info(f"  청크 {chunk['index']} 분석 완료 ({len(result):,}자)")
        except Exception as e:
            logger.error(f"  청크 {chunk['index']} 분석 실패: {e}")
            chunk_results.append(f"## chunk_{chunk['index']:02d} — 분석 실패: {e}")

    return chunk_results


def merge_results(
    chunk_results: list[str],
    vod_info: VODInfo,
    community_posts: list[CommunityPost],
    highlights: list[dict],
    claude_timeout: int = 300,
) -> str:
    """모든 청크 결과를 통합하여 최종 리포트 생성"""
    logger.info("최종 통합 요약 생성 중...")

    # 통합 프롬프트 로드
    merge_template = _load_merge_prompt()

    # 청크 결과 합치기 + 실패 청크 경고
    failed_count = sum(1 for r in chunk_results if "분석 실패:" in r)
    all_results = "\n\n---\n\n".join(chunk_results)
    if failed_count > 0:
        all_results = (
            f"⚠ 주의: 전체 {len(chunk_results)}개 청크 중 {failed_count}개가 분석에 실패했습니다. "
            f"실패한 구간은 '분석 실패'로 표시되어 있으며, 해당 구간은 건너뛰고 요약해주세요.\n\n"
            + all_results
        )

    # 커뮤니티 데이터 (방송 시작 시각을 전달하여 시간축 추론 가능하게)
    community_text = format_community_for_prompt(
        community_posts,
        broadcast_start=vod_info.publish_date,
    )

    # 하이라이트 요약
    highlight_text = ""
    if highlights:
        hl_lines = []
        for h in highlights[:10]:
            hl_lines.append(
                f"- [{sec_to_hms(h['sec'])}] 채팅수 {h['count']}개, "
                f"종합점수 {h['composite']:.4f}"
            )
        highlight_text = "\n".join(hl_lines)

    # 프롬프트 조립
    if "{CHUNK_RESULTS_ALL}" not in merge_template:
        logger.warning("통합 프롬프트에 {CHUNK_RESULTS_ALL} 플레이스홀더가 없습니다. 직접 조립합니다.")
        prompt = f"# 방송 분석 통합\n\n{all_results}"
    else:
        prompt = merge_template.replace("{CHUNK_RESULTS_ALL}", all_results)

    # 추가 컨텍스트 삽입
    context_section = f"""
## 방송 정보
- 방송 제목: {vod_info.title}
- 채널: {vod_info.channel_name}
- 카테고리: {vod_info.category}
- 방송 날짜: {vod_info.publish_date}
- 방송 길이: {sec_to_hms(vod_info.duration)}

## 채팅 기반 하이라이트 (Top 10)
{highlight_text if highlight_text else "(하이라이트 데이터 없음)"}

## 방송중 커뮤니티 글 내용 (현실시간 중계/요약, 부분적 관련 가능)
{community_text}
"""
    # 컨텍스트를 프롬프트 앞에 삽입
    prompt = context_section + "\n" + prompt

    # 토큰 초과 대응: 10개 이상 청크면 2라운드 병합
    if len(chunk_results) > 10:
        logger.info(f"  청크 {len(chunk_results)}개 → 2라운드 병합")
        return _two_round_merge(chunk_results, prompt, vod_info, community_posts, highlights, claude_timeout)

    try:
        result = call_claude(prompt, timeout=claude_timeout)
        logger.info(f"최종 리포트 생성 완료 ({len(result):,}자)")
        return result
    except Exception as e:
        logger.error(f"최종 리포트 생성 실패: {e}")
        # 폴백: 청크 결과를 단순 연결
        return f"# {vod_info.title} — 자동 요약 (통합 실패)\n\n{all_results}"


def _two_round_merge(
    chunk_results: list[str],
    merge_prompt: str,
    vod_info: VODInfo,
    community_posts: list[CommunityPost],
    highlights: list[dict],
    claude_timeout: int,
) -> str:
    """청크가 많을 때 2라운드 병합"""
    # 1라운드: 5개씩 중간 요약
    batch_size = 5
    mid_results = []
    for i in range(0, len(chunk_results), batch_size):
        batch = chunk_results[i:i + batch_size]
        batch_text = "\n\n---\n\n".join(batch)
        mid_prompt = f"""아래는 방송 "{vod_info.title}"의 일부 청크 분석 결과이다.
이를 하나의 연속된 요약으로 통합해줘. 중복을 제거하고 시간순으로 정리해줘.

{batch_text}"""
        try:
            mid_result = call_claude(mid_prompt, timeout=claude_timeout)
            mid_results.append(mid_result)
        except Exception as e:
            logger.warning(f"  중간 병합 실패: {e}")
            mid_results.append(batch_text[:3000])

    # 2라운드: 최종 통합
    final_prompt = merge_prompt.replace(
        "{CHUNK_RESULTS_ALL}",
        "\n\n---\n\n".join(mid_results)
    )
    try:
        return call_claude(final_prompt, timeout=claude_timeout)
    except Exception as e:
        logger.error(f"2라운드 최종 병합 실패: {e}")
        return "\n\n---\n\n".join(mid_results)


def generate_reports(
    summary: str,
    vod_info: VODInfo,
    highlights: list[dict],
    chats: list[dict],
    output_dir: str,
) -> tuple[str, str, str]:
    """Markdown + HTML + metadata JSON 저장"""
    os.makedirs(output_dir, exist_ok=True)
    from .utils import sanitize_filename

    date_str = ""
    if vod_info.publish_date:
        try:
            dt = datetime.fromisoformat(vod_info.publish_date.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y%m%d")
        except (ValueError, TypeError):
            date_str = datetime.now(KST).strftime("%Y%m%d")
    else:
        date_str = datetime.now(KST).strftime("%Y%m%d")

    base = f"{vod_info.video_no}_{date_str}_{sanitize_filename(vod_info.title)}"

    # Markdown
    md_path = os.path.join(output_dir, f"{base}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(summary)
    logger.info(f"Markdown 리포트 저장: {md_path}")

    # HTML
    html_path = os.path.join(output_dir, f"{base}.html")
    html_content = _generate_html(summary, vod_info, highlights, chats)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML 리포트 저장: {html_path}")

    # Metadata JSON
    meta_path = os.path.join(output_dir, f"{base}_metadata.json")
    metadata = {
        "video_no": vod_info.video_no,
        "title": vod_info.title,
        "channel": vod_info.channel_name,
        "duration": vod_info.duration,
        "publish_date": vod_info.publish_date,
        "category": vod_info.category,
        "total_chats": len(chats),
        "highlight_count": len(highlights),
        "highlights": [
            {"sec": h["sec"], "composite": h["composite"], "count": h["count"]}
            for h in highlights[:20]
        ],
        "processed_at": datetime.now(KST).isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return md_path, html_path, meta_path


def _generate_html(
    summary_md: str,
    vod_info: VODInfo,
    highlights: list[dict],
    chats: list[dict],
) -> str:
    """Markdown 요약을 시각적 HTML로 변환"""
    # 채팅 시계열 데이터 (차트용)
    from .chat_analyzer import build_time_series, WINDOW_SEC
    ts = build_time_series(chats, WINDOW_SEC) if chats else {"buckets": {}, "duration_sec": 0}
    bucket_keys = sorted(ts["buckets"].keys())
    chart_labels = json.dumps([sec_to_hms(k) for k in bucket_keys], ensure_ascii=False) if bucket_keys else "[]"
    chart_counts = json.dumps([ts["buckets"][k]["count"] for k in bucket_keys]) if bucket_keys else "[]"

    peak_secs = json.dumps([h["sec"] for h in highlights[:20]]) if highlights else "[]"

    # Markdown → HTML (블록 단위 변환)
    import re
    lines = summary_md.split("\n")
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # 빈 줄
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append("")
            continue

        # 헤더
        if stripped.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{stripped[4:]}</h3>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h2>{stripped[3:]}</h2>")
            continue
        if stripped.startswith("# "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h1>{stripped[2:]}</h1>")
            continue

        # 인용
        if stripped.startswith("> "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<blockquote>{stripped[2:]}</blockquote>")
            continue

        # 리스트 항목
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            html_parts.append(f"<li>{content}</li>")
            continue

        # 번호 리스트
        m = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if m:
            if not in_list:
                html_parts.append("<ol>")
                in_list = True  # 단순화: ol도 ul 플래그로 관리
            content = m.group(2)
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            html_parts.append(f"<li>{content}</li>")
            continue

        # 들여쓰기 (서브 항목)
        if line.startswith("    ") and in_list:
            content = stripped
            content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', content)
            html_parts.append(f"<li style='margin-left:20px'>{content}</li>")
            continue

        # 일반 텍스트
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
        html_parts.append(f"<p>{content}</p>")

    if in_list:
        html_parts.append("</ul>")

    html_body = "\n".join(html_parts)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{vod_info.title} — 방송 분석 리포트</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
  :root {{ --bg: #0d0f14; --surface: #161921; --surface2: #1e2230; --border: #2a2f42;
           --accent: #00ffa3; --accent2: #ff6b6b; --text: #e2e8f0; --muted: #64748b; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Noto Sans KR', sans-serif;
          min-height: 100vh; line-height: 1.7; }}
  header {{ padding: 32px 40px 20px; border-bottom: 1px solid var(--border);
            background: linear-gradient(135deg, #0d0f14 60%, #0d1f17); }}
  header h1 {{ font-size: 24px; font-weight: 700; }}
  header h1 span {{ color: var(--accent); }}
  header p {{ color: var(--muted); margin-top: 6px; font-size: 13px;
              font-family: 'JetBrains Mono', monospace; }}
  .stats {{ display: flex; gap: 24px; padding: 20px 40px; border-bottom: 1px solid var(--border);
            background: var(--surface); }}
  .stat {{ display: flex; flex-direction: column; gap: 2px; }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; }}
  .stat-value {{ font-size: 20px; font-weight: 700; font-family: 'JetBrains Mono', monospace;
                 color: var(--accent); }}
  .main {{ padding: 32px 40px; display: flex; flex-direction: column; gap: 32px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; }}
  .card h2 {{ font-size: 15px; color: var(--muted); text-transform: uppercase;
              letter-spacing: 1px; margin-bottom: 16px; }}
  .chart-wrap {{ height: 200px; position: relative; }}
  .content {{ line-height: 1.8; }}
  .content h1, .content h2, .content h3 {{ margin-top: 24px; margin-bottom: 12px; }}
  .content h2 {{ color: var(--accent); font-size: 20px; }}
  .content h3 {{ color: var(--text); font-size: 16px; }}
  .content li {{ margin-left: 20px; margin-bottom: 4px; }}
  .content blockquote {{ border-left: 3px solid var(--accent); padding-left: 16px;
                         color: var(--muted); font-style: italic; margin: 12px 0; }}
  .content strong {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>📋 <span>{vod_info.title}</span></h1>
  <p>{vod_info.channel_name} · {vod_info.publish_date} · {sec_to_hms(vod_info.duration)}</p>
</header>
<div class="stats">
  <div class="stat"><span class="stat-label">총 채팅</span><span class="stat-value">{len(chats):,}</span></div>
  <div class="stat"><span class="stat-label">방송 길이</span><span class="stat-value">{sec_to_hms(vod_info.duration)}</span></div>
  <div class="stat"><span class="stat-label">하이라이트</span><span class="stat-value">{len(highlights)}</span></div>
</div>
<div class="main">
  <div class="card">
    <h2>채팅 밀도 시각화</h2>
    <div class="chart-wrap"><canvas id="chatChart"></canvas></div>
  </div>
  <div class="card content">
    {html_body}
  </div>
</div>
<script>
const labels = {chart_labels};
const counts = {chart_counts};
const peakSecs = {peak_secs};
const windowSec = {WINDOW_SEC};
const peakSet = new Set(peakSecs.map(s => Math.floor(s / windowSec) * windowSec));
const bgColors = labels.map((_, i) =>
  peakSet.has(i * windowSec) ? 'rgba(255,107,107,0.85)' : 'rgba(0,255,163,0.55)'
);
new Chart(document.getElementById('chatChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: counts, backgroundColor: bgColors, borderWidth: 0, borderRadius: 2 }}] }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ x: {{ display: false }}, y: {{ grid: {{ color: 'rgba(255,255,255,0.05)' }},
              ticks: {{ color: '#64748b', font: {{ size: 11 }} }} }} }}
  }}
}});
</script>
</body>
</html>"""
