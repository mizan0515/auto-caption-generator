"""2단계 요약 오케스트레이션: 청크별 분석 → 통합 리포트

토큰 효율화 (2026-04-17 리팩토링):
  - Anthropic SDK 직접 호출 + 프롬프트 캐싱 (claude_cli.call_claude_cached)
  - 시스템 프롬프트(지시문)를 user 프롬프트(데이터)에서 분리
  - 시스템 프롬프트는 cache_control=ephemeral → 청크 간 캐싱 (input token ~90% 절감)
  - CLI fallback 시에는 합쳐서 전송 (기존 동작과 동일)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .chat_analyzer import format_chat_highlights_for_prompt, get_chats_in_range
from .claude_cli import call_claude_cached
from .models import VODInfo, CommunityPost
from .scraper import format_community_for_prompt
from .utils import sec_to_hms

logger = logging.getLogger("pipeline")

KST = timezone(timedelta(hours=9))

# 프롬프트 템플릿 경로
_MERGE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "청크 통합 프롬프트.md"

# Chart.js 에셋 경로 (self-hosted). _generate_html 에서 inline 으로 삽입해
# output/*.html 을 파일시스템에서 열든, site/vods/*/report.html 로 iframe 임베드
# 하든, 퍼블리시된 pages.dev 에서 로딩되든 동일하게 차트가 동작하도록 한다.
_CHARTJS_ASSET_PATH = (
    Path(__file__).resolve().parent.parent
    / "publish" / "web" / "assets" / "vendor" / "chart.umd.min.js"
)
_CHARTJS_INLINE_CACHE: Optional[str] = None


def _load_chartjs_inline() -> str:
    """Chart.js UMD 파일 내용을 읽어 inline <script> 에 넣을 문자열로 반환.
    파일이 없으면 빈 문자열 — 이 경우 _chartjs_script_tag() 가 relative path
    fallback 을 쓴다."""
    global _CHARTJS_INLINE_CACHE
    if _CHARTJS_INLINE_CACHE is not None:
        return _CHARTJS_INLINE_CACHE
    try:
        _CHARTJS_INLINE_CACHE = _CHARTJS_ASSET_PATH.read_text(encoding="utf-8")
    except OSError:
        _CHARTJS_INLINE_CACHE = ""
    return _CHARTJS_INLINE_CACHE


def _chartjs_script_tag() -> str:
    """Chart.js 를 HTML 에 주입하는 <script> 태그를 생성.

    publish/web/assets/vendor/chart.umd.min.js 를 인라인으로 임베드해
    output/*.html 직접 열기, site/vods/<id>/report.html iframe 로딩, pages.dev
    퍼블리시 3개 환경 모두에서 외부 네트워크 없이 차트가 동작하도록 한다.
    에셋 로드 실패 시에만 기존 relative path 로 폴백."""
    content = _load_chartjs_inline()
    if content:
        return f"<script>{content}</script>"
    return '<script src="../../assets/vendor/chart.umd.min.js"></script>'


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


# ── 청크 분석 시스템 프롬프트 (캐싱 대상) ──────────────────────

CHUNK_SYSTEM_PROMPT = """너는 한국 라이브 방송 분석 전문가야. 사용자가 제공하는 방송 자막과 채팅 데이터를 분석하여 해당 구간의 주요 순간을 타임라인으로 정리한다.

## 선정 기준 — 종합적으로 판단:
- 자막 내용이 드라마틱하거나 반전이 있거나 핵심 철학·인용이 나오는 순간
- 채팅 반응이 뜨거웠던 순간 (다만 채팅 피크만을 기준으로 삼지 말 것)
- 밈·유행어·별명이 탄생하거나 반복되는 순간
- 느슨한 잡담 구간도 맥락상 의미있으면 포함 (분위기 💬로)

## 포맷 (엄수)
- **[HH:MM:SS] 짧고 함축적인 세션명** (분위기: 🔥/💬/💤)
    - 내용: 1~2문장으로 무슨 일이 있었는지. 대표 발화 인용 OK. (`**`로 본문 안 강조 금지)
    - 근거: 실제 채팅 반응 2~3개를 짧은 따옴표로. "...", "..." 형식.

## 금지
- 내부 메트릭(점수, 확률, 퍼센트, 채팅수 등)을 근거에 노출하지 말 것
- 한 줄에 `**` 굵은 강조를 2회 이상 사용 금지 (제목 한 번만)
- 채팅 인용 외 "채팅 41개", "종합점수 0.7" 같은 숫자 근거 금지"""


def _build_chunk_user_prompt(
    chunk: dict,
    highlights: list[dict],
    chats: list[dict],
    vod_info: VODInfo,
) -> str:
    """개별 청크의 데이터-only 프롬프트 (시스템 프롬프트와 분리)"""
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

    prompt = f"""방송 "{vod_info.title}" 의 구간 ({chunk['start_hhmmss']} ~ {chunk['end_hhmmss']}) 분석:

## 채팅 하이라이트 (이 구간)
{chat_section if chat_section else "(채팅 데이터 없음)"}

## 자막 (Transcript)
{chunk['text']}"""
    return prompt


def _preslice_chats(chats: list[dict], start_ms: int, end_ms: int, margin_ms: int = 30_000) -> list[dict]:
    """청크 시간 범위에 해당하는 채팅만 추출 (bisect 사용, O(log n)).

    margin_ms: 하이라이트 context_sec 여유분 (기본 30초).
    chats는 ms 기준 정렬되어 있어야 한다.
    """
    import bisect
    if not chats:
        return []
    lo = bisect.bisect_left(chats, start_ms - margin_ms, key=lambda c: c["ms"])
    hi = bisect.bisect_right(chats, end_ms + margin_ms, key=lambda c: c["ms"])
    return chats[lo:hi]


def process_chunks(
    chunks: list[dict],
    highlights: list[dict],
    chats: list[dict],
    vod_info: VODInfo,
    claude_timeout: int = 300,
    claude_model: str = "",
    progress_func=None,
) -> list[str]:
    """각 청크를 Claude에 전달하여 분석.

    시스템 프롬프트(지시문)는 캐싱되어 첫 호출 이후 input token 비용 ~90% 절감.
    claude_model: 빈 문자열이면 기본 모델, "haiku" 등으로 경량 모델 지정 가능.

    B03: chats를 청크별로 미리 슬라이싱하여 전달 (50K 전체 스캔 방지).
    """
    # 채팅을 ms 기준 정렬 (보통 이미 정렬되어 있지만 보장)
    sorted_chats = sorted(chats, key=lambda c: c["ms"]) if chats else []

    chunk_results = []

    for chunk in chunks:
        # 청크 시간 범위의 채팅만 추출 (O(log n))
        chunk_chats = _preslice_chats(sorted_chats, chunk["start_ms"], chunk["end_ms"])
        user_prompt = _build_chunk_user_prompt(chunk, highlights, chunk_chats, vod_info)
        logger.info(
            f"  청크 {chunk['index']}/{len(chunks)} 분석 중 "
            f"({chunk['start_hhmmss']}~{chunk['end_hhmmss']}, {chunk['char_count']:,}자, "
            f"model={claude_model or 'default'})..."
        )

        try:
            result = call_claude_cached(
                user_prompt=user_prompt,
                system_prompt=CHUNK_SYSTEM_PROMPT,
                timeout=claude_timeout,
                model=claude_model,
            )
            chunk_results.append(f"## chunk_{chunk['index']:02d} ({chunk['start_hhmmss']}~{chunk['end_hhmmss']})\n\n{result}")
            logger.info(f"  청크 {chunk['index']} 분석 완료 ({len(result):,}자)")
        except Exception as e:
            logger.error(f"  청크 {chunk['index']} 분석 실패: {e}")
            chunk_results.append(f"## chunk_{chunk['index']:02d} — 분석 실패: {e}")

        # Heartbeat: 긴 VOD 의 청크 요약이 stale_after_sec (기본 1시간) 를 초과
        # 해 zombie detection 에 오판되지 않도록 매 청크 후 알림. 호출자가 내부
        # throttling 을 책임진다 (main.py 의 30s throttle).
        if progress_func:
            try:
                progress_func(chunk["index"], len(chunks))
            except Exception:  # noqa: BLE001
                pass

    return chunk_results


def _format_failure_notice_for_llm(failed_count: int, total_count: int) -> str:
    """Claude 입력에 prepend 할 실패 청크 지시문 (사용자에겐 보이면 안 됨).

    B22: 이전에는 이 문구를 `all_results` 에 직접 prepend 해서 merge fallback
    경로가 그대로 반환하면 사용자 리포트에 유출되었다. 이제는 호출자가
    Claude 에게 보낼 payload 에만 수동으로 prepend.
    """
    if failed_count <= 0:
        return ""
    return (
        f"⚠ 주의: 전체 {total_count}개 청크 중 {failed_count}개가 분석에 실패했습니다. "
        f"실패한 구간은 '분석 실패'로 표시되어 있으며, 해당 구간은 건너뛰고 요약해주세요.\n\n"
    )


def _build_failure_report(
    vod_info: VODInfo,
    chunk_results: list[str],
    failed_count: int,
    total_count: int,
    reason: str,
) -> str:
    """통합 머지 실패 시 사용자용 복구 가이드 리포트.

    B22: 이전 동작은 "# {title} — 자동 요약 (통합 실패)\\n\\n{all_results}" 로
    LLM 지시문("건너뛰고 요약해주세요")이 섞인 청크 덤프를 그대로 저장. 사용자는
    깨진 리포트만 보고 무엇을 해야 할지 모름. 이제는 원인/복구 명령을 명시.
    """
    # 실패 이유 1줄 요약 (traceback 노출 금지 → 로그에 맡김)
    reason_brief = (reason or "원인 미상").strip().splitlines()[0][:200]
    partial = "\n\n---\n\n".join(chunk_results) if chunk_results else "(청크 결과 없음)"
    return (
        f"# {vod_info.title} — 자동 요약 (통합 실패)\n"
        "\n"
        f"> ⚠ **최종 통합 요약 생성에 실패했습니다.** (실패 청크: {failed_count}/{total_count})\n"
        "\n"
        f"- 실패 원인(요약): `{reason_brief}`\n"
        f"- 상세 traceback 은 `output/logs/` 또는 실행 콘솔을 확인하세요.\n"
        "\n"
        "## 복구 방법\n"
        "\n"
        f"1. Claude CLI 가 설치/로그인되어 있는지 확인: `claude --version`\n"
        f"2. 네트워크/쿠키 문제라면 `pipeline_config.json` 검토 후 재실행\n"
        f"3. 같은 VOD 재처리: `python -m pipeline.main --process {vod_info.video_no}`\n"
        "\n"
        "## 부분 결과 (청크별 원문)\n"
        "\n"
        "아래는 통합 전 청크 결과 원문입니다. 수동으로 참고하거나 재실행 시 덮어써집니다.\n"
        "\n"
        f"{partial}\n"
    )


def merge_results(
    chunk_results: list[str],
    vod_info: VODInfo,
    community_posts: list[CommunityPost],
    highlights: list[dict],
    claude_timeout: int = 300,
    srt_path: str = "",
    claude_model: str = "",
    progress_func=None,
) -> str:
    """모든 청크 결과를 통합하여 최종 리포트 생성.

    progress_func(done, total): 2라운드 병합 시 각 round-1 batch 완료마다 호출.
    heartbeat 용도 — zombie detection 이 summarizing stage 를 false-positive 로
    잡지 않도록. 단일 라운드 경로에서는 시작/종료만 알린다.
    """
    logger.info("최종 통합 요약 생성 중...")
    if progress_func:
        try:
            progress_func(0, 1)
        except Exception:  # noqa: BLE001
            pass

    # 통합 프롬프트 로드
    merge_template = _load_merge_prompt()

    # 청크 결과 합치기 + 실패 청크 경고
    # B22: LLM-facing 지시문(prompt)과 user-facing 배너(report)를 분리.
    #   이전에는 LLM 지시문("건너뛰고 요약해주세요")을 all_results 에 prepend 해서
    #   merge 가 실패하면 line 303 fallback 이 그대로 반환 → output/*.md 에
    #   프롬프트 문구가 유출되던 UX 결함 (실측 12402235 리포트 참조).
    failed_count = sum(1 for r in chunk_results if "분석 실패:" in r)
    total_count = len(chunk_results)
    all_results = "\n\n---\n\n".join(chunk_results)
    llm_failure_notice = _format_failure_notice_for_llm(failed_count, total_count)

    # 커뮤니티 데이터
    community_text = format_community_for_prompt(
        community_posts,
        broadcast_start=vod_info.publish_date,
    )

    # 하이라이트 요약 (내부 메트릭 노출 금지 — B02)
    highlight_text = ""
    if highlights:
        from .chat_analyzer import _describe_intensity
        hl_lines = []
        for h in highlights[:10]:
            intensity = _describe_intensity(h)
            hl_lines.append(f"- [{sec_to_hms(h['sec'])}] 채팅 반응 {intensity}")
        highlight_text = "\n".join(hl_lines)

    # ── Multi-signal 하이라이트 후보 (자막 + 커뮤니티 매칭) ──
    # B08: SRT 를 1회만 파싱해서 두 분석에 공유 (find_subtitle_peaks +
    # build_community_signal 가 각각 parse_srt 하던 중복 제거).
    subtitle_signal_text = ""
    community_signal_text = ""
    if srt_path:
        shared_cues = None
        try:
            from .chunker import parse_srt
            shared_cues = parse_srt(srt_path)
            logger.info(f"  SRT 파싱 (공유): {len(shared_cues)}개 cue")
        except Exception as e:
            logger.warning(f"SRT 사전 파싱 실패 (각 분석이 자체 파싱하도록 fallback): {e}")

        try:
            from .subtitle_analyzer import find_subtitle_peaks, format_subtitle_signal_for_prompt
            peaks = find_subtitle_peaks(srt_path, window_sec=60, top_n=15, cues=shared_cues)
            subtitle_signal_text = format_subtitle_signal_for_prompt(peaks)
            logger.info(f"  자막 드라마틱 시그널: 상위 {len(peaks)}개 구간")
        except Exception as e:
            logger.warning(f"자막 시그널 분석 실패 (무시): {e}")

        if community_posts:
            try:
                from .community_matcher import build_community_signal, format_community_signal_for_prompt
                comm_sig = build_community_signal(community_posts, srt_path, cues=shared_cues)
                community_signal_text = format_community_signal_for_prompt(comm_sig)
            except Exception as e:
                logger.warning(f"커뮤니티 매칭 분석 실패 (무시): {e}")

    # ── 시스템 프롬프트 (캐싱) = 통합 지시문 + 메타 컨텍스트 ──
    merge_system = f"""## 방송 정보
- 방송 제목: {vod_info.title}
- 채널: {vod_info.channel_name}
- 카테고리: {vod_info.category}
- 방송 날짜: {vod_info.publish_date}
- 방송 길이: {sec_to_hms(vod_info.duration)}

---

# 🔎 Multi-signal 하이라이트 후보

아래 세 축의 시그널을 **종합적으로** 판단하여 최종 하이라이트를 선정하라.
어느 한 축의 숫자가 크다고 자동 선정하지 말 것. 3개 축이 교차하는 구간을 우선한다.

## 채팅 반응 기반 (Top 10) — 채팅 밀도 피크
{highlight_text if highlight_text else "(데이터 없음)"}

{subtitle_signal_text if subtitle_signal_text else "## 자막 드라마틱 시그널\\n(SRT 미주입)"}

{community_signal_text if community_signal_text else "## 커뮤니티 매칭\\n(데이터 없음)"}

---

## 방송중 커뮤니티 글 원문 (시간 축 불일치 — 맥락 참고용)
{community_text}"""

    # ── 유저 프롬프트 = 청크 결과 데이터 (LLM 지시문 prepend) ──
    chunk_payload = (llm_failure_notice + all_results) if llm_failure_notice else all_results
    if "{CHUNK_RESULTS_ALL}" not in merge_template:
        logger.warning("통합 프롬프트에 {CHUNK_RESULTS_ALL} 플레이스홀더가 없습니다. 직접 조립합니다.")
        user_prompt = f"# 방송 분석 통합\n\n{chunk_payload}"
    else:
        user_prompt = merge_template.replace("{CHUNK_RESULTS_ALL}", chunk_payload)

    # 토큰 초과 대응: 10개 이상 청크면 2라운드 병합
    if len(chunk_results) > 10:
        logger.info(f"  청크 {len(chunk_results)}개 → 2라운드 병합")
        return _two_round_merge(
            chunk_results, merge_template, merge_system,
            vod_info, community_posts, highlights, claude_timeout,
            claude_model=claude_model,
            progress_func=progress_func,
        )

    try:
        result = call_claude_cached(
            user_prompt=user_prompt,
            system_prompt=merge_system,
            timeout=claude_timeout,
            model=claude_model,
        )
        logger.info(f"최종 리포트 생성 완료 ({len(result):,}자)")
        return result
    except Exception as e:
        logger.error(f"최종 리포트 생성 실패: {e}")
        return _build_failure_report(vod_info, chunk_results, failed_count, total_count, reason=str(e))


def _two_round_merge(
    chunk_results: list[str],
    merge_template: str,
    merge_system: str,
    vod_info: VODInfo,
    community_posts: list[CommunityPost],
    highlights: list[dict],
    claude_timeout: int,
    claude_model: str = "",
    progress_func=None,
) -> str:
    """청크가 많을 때 2라운드 병합.

    Round 1: 5개씩 묶어 중간 요약 (시스템 프롬프트 캐싱)
    Round 2: 중간 요약을 최종 통합
    """
    batch_size = 5
    mid_system = f"""너는 방송 "{vod_info.title}" 의 청크 분석 결과를 통합하는 편집자다.
입력된 타임라인 항목들을 하나의 연속된 요약으로 통합하라.
중복을 제거하고 시간순으로 정리하라. 새로운 사건을 창작하지 말라."""

    mid_results = []
    for i in range(0, len(chunk_results), batch_size):
        batch = chunk_results[i:i + batch_size]
        batch_text = "\n\n---\n\n".join(batch)
        try:
            mid_result = call_claude_cached(
                user_prompt=batch_text,
                system_prompt=mid_system,
                timeout=claude_timeout,
                model=claude_model,
            )
            mid_results.append(mid_result)
        except Exception as e:
            logger.warning(f"  중간 병합 실패: {e}")
            mid_results.append(batch_text[:3000])
        # Heartbeat 용도 — 장시간 2라운드 병합이 zombie detection 에 안 걸리도록
        if progress_func:
            try:
                progress_func(i + batch_size, len(chunk_results))
            except Exception:  # noqa: BLE001
                pass

    # 2라운드: 최종 통합
    final_user = merge_template.replace(
        "{CHUNK_RESULTS_ALL}",
        "\n\n---\n\n".join(mid_results)
    )
    try:
        return call_claude_cached(
            user_prompt=final_user,
            system_prompt=merge_system,
            timeout=claude_timeout,
            model=claude_model,
        )
    except Exception as e:
        logger.error(f"2라운드 최종 병합 실패: {e}")
        # B22: 2라운드 fallback 도 user-facing 배너 + 중간 결과로.
        failed_count = sum(1 for r in chunk_results if "분석 실패:" in r)
        partial = "\n\n---\n\n".join(mid_results)
        return _build_failure_report(
            vod_info, [partial], failed_count, len(chunk_results),
            reason=f"2라운드 병합 실패: {e}",
        )


def generate_reports(
    summary: str,
    vod_info: VODInfo,
    highlights: list[dict],
    chats: list[dict],
    output_dir: str,
    community_posts: list = None,
    public_url_base: str = "",
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

    # 마크다운 최상단에 공유용 링크 prepend (요약 웹페이지 + 치지직 다시보기).
    # .md 와 .html 양쪽이 동일 내용을 공유하도록 summary 자체를 수정.
    header_links = _build_header_links_md(vod_info, public_url_base)
    if header_links and header_links not in summary:
        summary = header_links + "\n\n" + summary

    # 각 산출물은 독립적으로 처리한다. 하나가 실패해도 나머지는 살린다.
    # - Markdown 은 summary 그 자체이므로 절대 실패해선 안 된다 (OSError 만 예외).
    # - HTML 은 Claude 출력 파싱(정규식/섹션 분해) 이슈로 종종 깨진다. 실패 시
    #   minimal HTML 로 폴백해서 적어도 브라우저에서 뭔가는 보이게 한다.
    # - Metadata JSON 은 부가 정보라 실패하면 건너뛴다.
    md_path = os.path.join(output_dir, f"{base}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(summary)
    logger.info(f"Markdown 리포트 저장: {md_path}")

    html_path = os.path.join(output_dir, f"{base}.html")
    try:
        html_content = _generate_html(summary, vod_info, highlights, chats, community_posts, public_url_base)
    except Exception as e:  # noqa: BLE001
        # _generate_html 의 정규식/섹션 파싱이 에지케이스 Claude 출력에서 깨지는
        # 경우, 이전엔 함수 전체가 raise 되어 md 가 디스크엔 있지만 result 에는
        # 기록 못한 채 VOD 가 error 로 끝났다. → minimal HTML 로 폴백.
        logger.warning(f"HTML 렌더링 실패 — minimal fallback 사용: {e}")
        import html as _html
        html_content = (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(vod_info.title)}</title></head>"
            f"<body><h1>{_html.escape(vod_info.title)}</h1>"
            f"<p><em>HTML 렌더링 실패 — 원본 Markdown 을 보세요: "
            f"<code>{_html.escape(os.path.basename(md_path))}</code></em></p>"
            f"<pre style='white-space:pre-wrap'>{_html.escape(summary)}</pre>"
            f"</body></html>"
        )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML 리포트 저장: {html_path}")

    # Metadata JSON — 실패해도 md/html 은 이미 살아있으므로 스킵 허용
    meta_path = os.path.join(output_dir, f"{base}_metadata.json")
    metadata = {
        "video_no": vod_info.video_no,
        "title": vod_info.title,
        "channel": vod_info.channel_name,
        "channel_id": vod_info.channel_id,
        "streamer_id": vod_info.streamer_id,
        "platform": "chzzk",
        "duration": vod_info.duration,
        "publish_date": vod_info.publish_date,
        "category": vod_info.category,
        "thumbnail_url": vod_info.thumbnail_url or None,
        "total_chats": len(chats),
        "highlight_count": len(highlights),
        "highlights": [
            {"sec": h["sec"], "composite": h["composite"], "count": h["count"]}
            for h in highlights[:20]
        ],
        "processed_at": datetime.now(KST).isoformat(),
    }
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except (OSError, TypeError, ValueError) as e:
        # 부가정보 실패로 전체 VOD 를 error 처리하지 않는다.
        logger.warning(f"메타데이터 저장 실패 (md/html 은 살아있음): {e}")

    return md_path, html_path, meta_path


def _parse_summary_sections(md: str) -> dict:
    """Claude 요약 Markdown을 섹션별로 구조화.

    반환: {
      'title': str, 'hashtags': [str], 'pull_quote': str,
      'timeline': [{'tc': '00:26:06', 'title': '...', 'mood': 'hot|chat|chill|veryhot',
                    'summary': '...', 'evidence': '...'}],
      'highlights': [{'tc_range': '...', 'title': '...', 'reason': '...'}],
      'editor_notes': [paragraphs],
      'raw_fallback': full md (파싱 실패 시 원본 렌더링용)
    }
    """
    import re

    out = {
        "title": "", "hashtags": [], "pull_quote": "",
        "timeline": [], "highlights": [], "editor_notes": [],
        "raw_fallback": md,
    }

    # 제목 (첫 ## 헤더)
    m = re.search(r"^##\s+.*?방송 분석 리포트\s*:\s*(.+)$", md, flags=re.M)
    if m:
        out["title"] = m.group(1).strip()

    # 해시태그 — `#태그` 또는 #태그 형태를 넓게 수집
    m = re.search(r"핵심 요약[:\*\s]*(.+)", md)
    if m:
        tags = re.findall(r"[`#]+([\w가-힣]+)", m.group(1))
        seen = set()
        out["hashtags"] = [t for t in tags if not (t in seen or seen.add(t))]

    # pull quote — 첫 blockquote
    m = re.search(r'^\s*>\s*"?(.+?)"?\s*$', md, flags=re.M)
    if m:
        out["pull_quote"] = m.group(1).strip().strip('"')

    # 타임라인 섹션 추출 (B09: 헤더 emoji optional, 엔트리 패턴 다중 fallback)
    tl_match = re.search(
        r"###\s*(?:📍\s*)?[^\n]*타임라인[^\n]*\n(.+?)(?=\n###\s|\Z)",
        md, flags=re.S
    )
    if tl_match:
        tl_body = tl_match.group(1)
        # 분리: HH:MM:SS 가 들어간 새 bullet 라인을 경계로
        # 분리: HH:MM:SS 가 들어간 새 bullet 라인 경계
        # 허용 형태: `- **[HH:MM:SS]`, `- [HH:MM:SS]`, `- HH:MM:SS`, `* **[HH:MM:SS]`
        entries = re.split(r"\n(?=\s*[-*]\s*\**\s*\[?\d{2}:\d{2}:\d{2}\]?)", tl_body)
        # 엔트리 패턴 (strict → loose 순으로 시도)
        _entry_patterns = [
            # strict: - **[HH:MM:SS] title**
            re.compile(
                r"\s*[-*]\s*\*\*\s*\[(\d{2}:\d{2}:\d{2})\]\s*(.+?)\*\*\s*(?:\(분위기:\s*(.+?)\))?"
            ),
            # loose A: - [HH:MM:SS] **title** (분위기: ...)
            re.compile(
                r"\s*[-*]\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*\*\*(.+?)\*\*\s*(?:\(분위기:\s*(.+?)\))?"
            ),
            # loose B: - [HH:MM:SS] title — desc (no bold, dash separator)
            re.compile(
                r"\s*[-*]\s*\[?(\d{2}:\d{2}:\d{2})\]?\s*(.+?)(?:\s*[—\-–]\s*|$)(?:\(분위기:\s*(.+?)\))?"
            ),
        ]
        for ent in entries:
            em = None
            for pat in _entry_patterns:
                em = pat.match(ent)
                if em:
                    break
            if not em:
                continue
            tc, title, mood_raw = em.group(1), em.group(2).strip(), (em.group(3) or "").strip()

            mood = "chill"
            if "🔥🔥" in mood_raw:
                mood = "veryhot"
            elif "🔥" in mood_raw:
                mood = "hot"
            elif "💬" in mood_raw:
                mood = "chat"
            elif "💤" in mood_raw:
                mood = "chill"

            summary_lines = re.findall(r"내용\s*[:：]\s*(.+)", ent)
            evidence_lines = re.findall(r"근거\s*[:：]\s*(.+)", ent)
            summary_text = " ".join(s.strip() for s in summary_lines) or ""
            evidence_text = " ".join(e.strip() for e in evidence_lines) or ""

            title = title.rstrip(" *`").strip()

            out["timeline"].append({
                "tc": tc,
                "title": title,
                "mood": mood,
                "mood_raw": mood_raw,
                "summary": summary_text,
                "evidence": evidence_text,
            })

    # 하이라이트 섹션 (B09: 헤더 emoji optional)
    hl_match = re.search(
        r"###\s*(?:🎬\s*)?[^\n]*하이라이트[^\n]*\n(.+?)(?=\n###\s|\Z)",
        md, flags=re.S
    )
    if hl_match:
        hl_body = hl_match.group(1)
        for em in re.finditer(
            r"^\s*(\d+)\.\s*\*\*\[?(\d{2}:\d{2}:\d{2}(?:~\d{2}:\d{2}:\d{2})?)\]?\*?\*?\s*(.+?)\*?\*?\s*$",
            hl_body, flags=re.M
        ):
            tc_range = em.group(2)
            title_raw = em.group(3).strip()
            rm = re.match(r"(.+?)\s*\(?추천 이유[:：]\s*(.+?)\)?\s*$", title_raw)
            if rm:
                title, reason = rm.group(1).strip(" *"), rm.group(2).strip(" *")
            else:
                title, reason = title_raw.strip(" *"), ""
            out["highlights"].append({
                "tc_range": tc_range,
                "title": title,
                "reason": reason,
            })

    # 에디터 후기 섹션 (B09: 헤더 emoji optional)
    ed_match = re.search(
        r"###\s*(?:📝\s*)?[^\n]*(?:에디터|후기)[^\n]*\n(.+?)(?=\n###\s|\Z)",
        md, flags=re.S
    )
    if ed_match:
        body = ed_match.group(1).strip()
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        out["editor_notes"] = paragraphs

    return out


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _render_inline_md(s: str) -> str:
    """간단한 인라인 마크다운(**strong**, `code`, [text](url)) → HTML"""
    import re
    s = _html_escape(s)
    # [text](http...) → <a>. escape 후이므로 URL 의 & 는 이미 &amp; 로 치환돼 있다.
    s = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        s,
    )
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _build_header_links_md(vod_info: VODInfo, public_url_base: str) -> str:
    """요약 .md 상단에 prepend 할 공유용 링크 블록을 반환.

    SNS 미리보기용 OG 메타태그는 report.html 에 붙이므로 URL 은 report.html
    직접 경로(Cloudflare 가 .html 를 자동 strip) 를 사용한다.
    """
    lines: list[str] = []
    if public_url_base:
        report_url = f"{public_url_base.rstrip('/')}/vods/{vod_info.video_no}/report"
        lines.append(f"- **🔗 요약 웹페이지:** [{report_url}]({report_url})")
    if vod_info.video_no:
        chzzk_url = f"https://chzzk.naver.com/video/{vod_info.video_no}"
        lines.append(f"- **▶️ 치지직 다시보기:** [{chzzk_url}]({chzzk_url})")
    return "\n".join(lines)


def _build_og_meta(vod_info: VODInfo, summary_md: str, public_url_base: str,
                   sec: dict) -> str:
    """OG/Twitter 메타 태그 블록 생성 (report.html 용).

    description 은 hashtags + pull_quote 조합 우선, 없으면 summary 첫 200자.
    """
    title = f"{vod_info.title} — 방송 분석 리포트"
    if vod_info.channel_name:
        title = f"[{vod_info.channel_name}] {title}"

    desc_parts = []
    if sec.get("hashtags"):
        desc_parts.append(" ".join(f"#{t}" for t in sec["hashtags"][:6]))
    if sec.get("pull_quote"):
        desc_parts.append(sec["pull_quote"])
    description = " — ".join(desc_parts) if desc_parts else summary_md[:200].replace("\n", " ")
    if len(description) > 300:
        description = description[:297] + "..."

    og_url = ""
    if public_url_base:
        og_url = f"{public_url_base.rstrip('/')}/vods/{vod_info.video_no}/report"

    image_tags = ""
    if vod_info.thumbnail_url:
        image_tags = (
            f'<meta property="og:image" content="{_html_escape(vod_info.thumbnail_url)}">\n'
            f'<meta name="twitter:image" content="{_html_escape(vod_info.thumbnail_url)}">\n'
        )
    card_type = "summary_large_image" if vod_info.thumbnail_url else "summary"

    tags = [
        f'<meta property="og:type" content="article">',
        f'<meta property="og:site_name" content="auto-caption-generator">',
        f'<meta property="og:title" content="{_html_escape(title)}">',
        f'<meta property="og:description" content="{_html_escape(description)}">',
    ]
    if og_url:
        tags.append(f'<meta property="og:url" content="{_html_escape(og_url)}">')
    tags.append(f'<meta name="twitter:card" content="{card_type}">')
    tags.append(f'<meta name="twitter:title" content="{_html_escape(title)}">')
    tags.append(f'<meta name="twitter:description" content="{_html_escape(description)}">')
    return image_tags + "\n".join(tags)


def _generate_html(
    summary_md: str,
    vod_info: VODInfo,
    highlights: list[dict],
    chats: list[dict],
    community_posts: list = None,
    public_url_base: str = "",
) -> str:
    """구조화된 카드 레이아웃 HTML 렌더링 (Tokyo Night 팔레트, 중앙 정렬)"""
    from .chat_analyzer import build_time_series, WINDOW_SEC

    # 채팅 시계열 데이터 (차트용)
    ts = build_time_series(chats, WINDOW_SEC) if chats else {"buckets": {}, "duration_sec": 0}
    bucket_keys = sorted(ts["buckets"].keys())
    chart_labels = json.dumps([sec_to_hms(k) for k in bucket_keys], ensure_ascii=False) if bucket_keys else "[]"
    chart_counts = json.dumps([ts["buckets"][k]["count"] for k in bucket_keys]) if bucket_keys else "[]"
    peak_secs = json.dumps([h["sec"] for h in highlights[:20]]) if highlights else "[]"

    # 요약 구조화
    sec = _parse_summary_sections(summary_md)
    title_display = sec["title"] or vod_info.title
    comm_count = len(community_posts) if community_posts else 0

    # ── 히어로 섹션 (해시태그 + pull quote)
    tag_chips = ""
    if sec["hashtags"]:
        tag_chips = "\n".join(
            f'<span class="tag">#{_html_escape(t)}</span>' for t in sec["hashtags"][:6]
        )

    pull_quote_html = ""
    if sec["pull_quote"]:
        pull_quote_html = f'<div class="quote">"{_html_escape(sec["pull_quote"])}"</div>'

    hero_html = ""
    if tag_chips or pull_quote_html:
        hero_html = f'''
<div class="hero"><div class="bleed-inner">
  {f'<div class="tags">{tag_chips}</div>' if tag_chips else ''}
  {pull_quote_html}
</div></div>'''

    # ── 타임라인 카드들
    timeline_html = ""
    if sec["timeline"]:
        items = []
        for t in sec["timeline"]:
            mood_class = f"mood-{t['mood']}"
            mood_emoji = t["mood_raw"] or {"hot": "🔥", "veryhot": "🔥🔥", "chat": "💬", "chill": "💤"}.get(t["mood"], "")
            evidence_html = ""
            if t["evidence"]:
                evidence_html = f'<div class="t-evidence">{_render_inline_md(t["evidence"])}</div>'
            items.append(f'''
<div class="t-item {mood_class}">
  <div class="t-head">
    <span class="tc">{t["tc"]}</span>
    <span class="t-title">{_render_inline_md(t["title"])}</span>
    <span class="mood">{_html_escape(mood_emoji)}</span>
  </div>
  <div class="t-body">{_render_inline_md(t["summary"])}</div>
  {evidence_html}
</div>''')
        timeline_html = f'''
<div class="card">
  <div class="card-head">
    <h2>📍 타임라인 상세</h2>
    <button class="t-toggle" onclick="toggleAll(this)">근거 모두 펼치기</button>
  </div>
  <div class="card-body">
    <div class="timeline">{''.join(items)}</div>
  </div>
</div>'''

    # ── 하이라이트 카드
    highlights_html = ""
    if sec["highlights"]:
        items = []
        for h in sec["highlights"]:
            reason_html = f'<div class="hl-reason">{_render_inline_md(h["reason"])}</div>' if h["reason"] else ""
            items.append(f'''
<div class="hl">
  <div class="hl-body">
    <div class="hl-title"><span class="tc">{_html_escape(h["tc_range"])}</span>&nbsp;&nbsp;{_render_inline_md(h["title"])}</div>
    {reason_html}
  </div>
</div>''')
        highlights_html = f'''
<div class="card">
  <div class="card-head"><h2>🎬 하이라이트 추천</h2></div>
  <div class="card-body"><div class="hl-list">{''.join(items)}</div></div>
</div>'''

    # ── 에디터 후기 카드
    notes_html = ""
    if sec["editor_notes"]:
        paras = "\n".join(f'<p>{_render_inline_md(p)}</p>' for p in sec["editor_notes"])
        notes_html = f'''
<div class="card">
  <div class="card-head"><h2>📝 에디터의 방송 후기</h2></div>
  <div class="card-body"><div class="notes">{paras}</div></div>
</div>'''

    # ── Raw markdown fallback (B09: 항상 렌더링하되 구조화 실패 여부에 따라 표시 방식 변경)
    #    - 전체 파싱 실패: 펼친 카드로 표시 (사용자가 곧장 본문 확인)
    #    - 부분 파싱: <details> 로 접어두기 (raw 원본 보존, 필요 시 펼침)
    import re
    body = _html_escape(summary_md)
    body = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", body, flags=re.M)
    body = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", body, flags=re.M)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    # [text](http...) → <a>. prepended 요약 웹페이지 / 치지직 링크를 클릭 가능하게.
    body = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        r'<a href="\2" target="_blank" rel="noopener" style="color:var(--accent);word-break:break-all">\1</a>',
        body,
    )
    body = body.replace("\n\n", "</p><p>")

    all_empty = not any([sec["timeline"], sec["highlights"], sec["editor_notes"]])
    if all_empty:
        fallback_html = (
            f'<div class="card"><div class="card-head"><h2>📄 원본 요약 (구조화 파싱 실패)</h2></div>'
            f'<div class="card-body"><div class="notes"><p>{body}</p></div></div></div>'
        )
    else:
        fallback_html = (
            f'<div class="card"><div class="card-body">'
            f'<details><summary style="cursor:pointer;color:var(--muted);font-family:monospace;font-size:13px">'
            f'📄 원본 요약 마크다운 보기</summary>'
            f'<div class="notes" style="margin-top:16px"><p>{body}</p></div></details></div></div>'
        )

    # ── 날짜 포맷 정돈
    pub_display = vod_info.publish_date
    try:
        from datetime import datetime as _dt
        pub_display = _dt.fromisoformat(vod_info.publish_date.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    og_meta = _build_og_meta(vod_info, summary_md, public_url_base, sec)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html_escape(vod_info.title)} — 방송 분석 리포트</title>
{og_meta}
{_chartjs_script_tag()}
<style>
  /* Self-hosted assets: no external CDN. Fonts use OS-installed fallbacks. */
  :root {{
    --bg:          #1a1b26;
    --surface:     #24283b;
    --surface-2:   #2a2f43;
    --border:      #363b54;
    --border-soft: #2e3248;
    --text:        #c0caf5;
    --text-strong: #e8ebf3;
    --muted:       #7982a9;
    --faint:       #565c7e;
    --tc:          #7aa2f7;
    --mood-hot:    #f7768e;
    --mood-chat:   #bb9af7;
    --mood-chill:  #7dcfff;
    --accent:      #9ece6a;
    --accent-warm: #e0af68;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: var(--bg); color: var(--text); }}
  body {{ font-family: 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', '맑은 고딕', system-ui, -apple-system, 'Segoe UI', sans-serif; min-height: 100vh; line-height: 1.7; font-size: 15px; }}

  /* Centered Layout */
  .bleed-inner {{ max-width: 960px; margin: 0 auto; padding: 0 40px; }}

  header {{
    border-bottom: 1px solid var(--border);
    background: radial-gradient(ellipse at top left, rgba(122,162,247,0.08), transparent 60%), var(--bg);
  }}
  header .bleed-inner {{ padding: 36px 40px 28px; }}
  header .crumb {{ font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; color: var(--muted); font-size: 12px;
                   letter-spacing: 0.5px; margin-bottom: 10px; }}
  header h1 {{ font-size: 26px; font-weight: 700; color: var(--text-strong); line-height: 1.35; letter-spacing: -0.3px; }}
  header .meta {{ color: var(--muted); margin-top: 10px; font-size: 13px; font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; }}
  header .meta span + span::before {{ content: "·"; margin: 0 10px; color: var(--faint); }}

  .hero {{ background: var(--surface); border-bottom: 1px solid var(--border); }}
  .hero .bleed-inner {{ padding: 28px 40px; }}
  .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }}
  .tag {{
    display: inline-block; padding: 6px 14px;
    background: rgba(158,206,106,0.12); color: var(--accent);
    border: 1px solid rgba(158,206,106,0.28); border-radius: 999px;
    font-size: 13px; font-weight: 600; font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace;
  }}
  .quote {{
    font-size: 17px; color: var(--text-strong); font-weight: 500; line-height: 1.55;
    padding-left: 16px; border-left: 3px solid var(--accent-warm); font-style: italic;
  }}

  .stats-wrap {{ background: var(--surface); border-bottom: 1px solid var(--border); }}
  .stats-wrap .bleed-inner {{ padding: 0; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--border-soft); }}
  .stat {{ background: var(--surface); padding: 18px 24px; }}
  .stat-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase;
                 letter-spacing: 1.2px; margin-bottom: 6px; }}
  .stat-value {{ font-size: 22px; font-weight: 700; font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; color: var(--text-strong); }}
  .stat-value.accent {{ color: var(--tc); }}

  .main {{ padding-top: 32px; padding-bottom: 60px; display: flex; flex-direction: column; gap: 28px; }}

  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
  .card-head {{ padding: 18px 24px; border-bottom: 1px solid var(--border-soft);
                display: flex; align-items: center; justify-content: space-between; }}
  .card-head h2 {{ font-size: 13px; color: var(--muted); text-transform: uppercase;
                    letter-spacing: 1.5px; font-weight: 600; }}
  .card-body {{ padding: 24px; }}
  .chart-wrap {{ height: 220px; position: relative; }}

  .timeline {{ display: flex; flex-direction: column; gap: 12px; }}
  .t-item {{
    padding: 16px 20px 16px 18px; background: var(--surface-2); border-radius: 8px;
    border-left: 3px solid var(--border); transition: background 0.15s; cursor: pointer;
  }}
  .t-item:hover {{ background: #2e334b; }}
  .t-item.mood-hot {{ border-left-color: var(--mood-hot); }}
  .t-item.mood-chat {{ border-left-color: var(--mood-chat); }}
  .t-item.mood-chill {{ border-left-color: var(--mood-chill); }}
  .t-item.mood-veryhot {{ border-left-color: var(--mood-hot); border-left-width: 5px;
                          box-shadow: inset 3px 0 0 var(--mood-hot); }}
  .t-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }}
  .tc {{
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; font-size: 12px; font-weight: 600;
    color: var(--tc); background: rgba(122,162,247,0.12);
    padding: 3px 9px; border-radius: 4px; letter-spacing: 0.3px;
  }}
  .t-title {{ font-size: 15px; font-weight: 600; color: var(--text-strong); }}
  .mood {{ font-size: 14px; margin-left: auto; }}
  .t-body {{ color: var(--text); font-size: 14px; line-height: 1.65; }}
  .t-evidence {{
    margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border-soft);
    color: var(--faint); font-size: 12px; line-height: 1.55;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; display: none;
  }}
  .t-item[data-open="1"] .t-evidence {{ display: block; }}

  .t-toggle {{
    font-size: 11px; color: var(--muted); cursor: pointer; user-select: none;
    padding: 4px 10px; border: 1px solid var(--border); border-radius: 4px;
    background: transparent; font-family: inherit;
  }}
  .t-toggle:hover {{ color: var(--text); border-color: var(--muted); }}

  .hl-list {{ display: flex; flex-direction: column; gap: 12px; counter-reset: hl; }}
  .hl {{ display: flex; gap: 16px; padding: 16px 20px; background: var(--surface-2);
         border-radius: 8px; counter-increment: hl; }}
  .hl::before {{
    content: counter(hl); font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace;
    font-size: 22px; font-weight: 700; color: var(--accent-warm); min-width: 28px;
  }}
  .hl-body {{ flex: 1; }}
  .hl-title {{ font-weight: 600; color: var(--text-strong); margin-bottom: 4px; }}
  .hl-reason {{ color: var(--muted); font-size: 13px; }}

  .notes {{ color: var(--text); font-size: 14.5px; line-height: 1.85; }}
  .notes p {{ margin-bottom: 14px; }}
  .notes p:last-child {{ margin-bottom: 0; }}
  .notes strong {{ color: var(--text-strong); font-weight: 600; }}
  code {{ font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace; font-size: 0.92em;
          background: var(--surface-2); padding: 1px 6px; border-radius: 4px; color: var(--accent); }}

  ::-webkit-scrollbar {{ width: 10px; height: 10px; }}
  ::-webkit-scrollbar-track {{ background: var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 5px; }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}

  @media (max-width: 720px) {{
    .bleed-inner {{ padding-left: 20px; padding-right: 20px; }}
    header .bleed-inner {{ padding: 28px 20px 20px; }}
    .hero .bleed-inner {{ padding: 22px 20px; }}
    header h1 {{ font-size: 22px; }}
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>

<header><div class="bleed-inner">
  <div class="crumb">{_html_escape(vod_info.channel_name)} · VOD {_html_escape(vod_info.video_no)}</div>
  <h1>{_html_escape(title_display)}</h1>
  <div class="meta">
    <span>{_html_escape(pub_display)}</span>
    <span>{sec_to_hms(vod_info.duration)}</span>
    {f'<span>{_html_escape(vod_info.category)}</span>' if vod_info.category else ''}
  </div>
</div></header>

{hero_html}

<div class="stats-wrap"><div class="bleed-inner"><div class="stats">
  <div class="stat"><div class="stat-label">총 채팅</div><div class="stat-value accent">{len(chats):,}</div></div>
  <div class="stat"><div class="stat-label">방송 길이</div><div class="stat-value">{sec_to_hms(vod_info.duration)}</div></div>
  <div class="stat"><div class="stat-label">하이라이트</div><div class="stat-value accent">{len(highlights)}</div></div>
  <div class="stat"><div class="stat-label">커뮤니티 글</div><div class="stat-value">{comm_count}</div></div>
</div></div></div>

<div class="main bleed-inner">

  <div class="card">
    <div class="card-head"><h2>채팅 밀도 시각화</h2></div>
    <div class="card-body"><div class="chart-wrap"><canvas id="chatChart"></canvas></div></div>
  </div>

  {timeline_html}
  {highlights_html}
  {notes_html}
  {fallback_html}

</div>

<script>
const labels = {chart_labels};
const counts = {chart_counts};
const peakSecs = {peak_secs};
const windowSec = {WINDOW_SEC};
const peakSet = new Set(peakSecs.map(s => Math.floor(s / windowSec) * windowSec));
const bgColors = labels.map((_, i) =>
  peakSet.has(i * windowSec) ? 'rgba(247,118,142,0.75)' : 'rgba(122,162,247,0.35)'
);
if (labels.length > 0) {{
  new Chart(document.getElementById('chatChart'), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: counts, backgroundColor: bgColors, borderWidth: 0, borderRadius: 2 }}] }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }}, tooltip: {{
        backgroundColor: '#24283b', borderColor: '#363b54', borderWidth: 1,
        titleColor: '#c0caf5', bodyColor: '#c0caf5'
      }}}},
      scales: {{
        x: {{ grid: {{ display: false }}, ticks: {{ color: '#565c7e', font: {{ size: 10 }}, maxTicksLimit: 12 }} }},
        y: {{ grid: {{ color: 'rgba(255,255,255,0.04)' }}, ticks: {{ color: '#565c7e', font: {{ size: 11 }} }} }}
      }}
    }}
  }});
}}

// 타임라인 아이템 클릭 시 근거 토글
document.querySelectorAll('.t-item').forEach(item => {{
  item.addEventListener('click', (e) => {{
    if (e.target.tagName === 'BUTTON') return;
    const open = item.getAttribute('data-open') === '1';
    item.setAttribute('data-open', open ? '0' : '1');
  }});
}});
function toggleAll(btn) {{
  const items = document.querySelectorAll('.t-item');
  const anyClosed = Array.from(items).some(i => i.getAttribute('data-open') !== '1');
  items.forEach(i => i.setAttribute('data-open', anyClosed ? '1' : '0'));
  btn.textContent = anyClosed ? '근거 모두 접기' : '근거 모두 펼치기';
}}
</script>

</body>
</html>"""
