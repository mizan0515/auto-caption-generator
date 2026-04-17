"""
Chzzk VOD 자동 모니터링 & 요약 파이프라인 — 메인 오케스트레이터

사용법:
  python -m pipeline.main                   # 데몬 모드 (포그라운드)
  pythonw -m pipeline.main                  # 데몬 모드 (백그라운드)
  python -m pipeline.main --once            # 1회 실행 후 종료
  python -m pipeline.main --process <VOD번호>  # 특정 VOD 수동 처리
  python -m pipeline.main --process <VOD번호> --limit-duration 1800  # 앞 30분만 테스트
  python -m pipeline.main --setup-cookies   # 쿠키 대화형 설정
"""

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# B14/B15: Windows cp949 콘솔 한글 깨짐 방지 (pythonw/리다이렉트는 무음 폴백)
from ._io_encoding import force_utf8_stdio  # noqa: E402
force_utf8_stdio()

from .config import (
    load_config, save_config, get_cookies, ensure_dirs,
    validate_cookies, interactive_cookie_setup,
    normalize_streamers, derive_streamer_id,
    ConfigError,
)
from .state import PipelineState
from .monitor import check_new_vods
from .downloader import download_vod_144p
from .chat_collector import fetch_all_chats, save_chat_log
from .chat_analyzer import find_edit_points
from .transcriber import transcribe_video
from .chunker import chunk_srt
from .scraper import scrape_fmkorea
from .summarizer import process_chunks, merge_results, generate_reports
from .models import VODInfo, PipelineResult
from .utils import setup_logging, sec_to_hms, format_duration, clip_video


def _vod_age_hours(publish_date: str) -> float | None:
    """VOD publish_date(ISO) → 현재까지 경과 시간(시간 단위). 파싱 실패 시 None.

    fmkorea 시간 필터링과 동일 KST 기준으로 비교 (scraper.KST = +09:00).
    """
    if not publish_date:
        return None
    try:
        from datetime import datetime, timedelta, timezone
        kst = timezone(timedelta(hours=9))
        dt = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=kst)
        delta = datetime.now(kst) - dt
        return delta.total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def _should_skip_fmkorea(publish_date: str, max_age_hours: int) -> tuple[bool, str]:
    """B11: VOD 가 max_age_hours 이전이면 fmkorea 스킵 결정.

    반환: (skip?, 이유 메시지). max_age_hours <= 0 이면 항상 (False, "")
    """
    if max_age_hours <= 0:
        return False, ""
    age = _vod_age_hours(publish_date)
    if age is None:
        # 파싱 실패는 스킵하지 않음 (fail-safe: 시도는 해본다)
        return False, ""
    if age > max_age_hours:
        return True, f"VOD 가 {age:.1f}시간 전 ({max_age_hours}h 임계 초과)"
    return False, ""


def _try_auto_publish(cfg: dict, result: 'PipelineResult', state: PipelineState, logger):
    """VOD 처리 성공 후 자동 퍼블리시를 시도한다. 실패해도 예외를 흘리지 않는다."""
    try:
        from publish.hook import auto_publish_after_vod
        pub_result = auto_publish_after_vod(
            cfg,
            result_md=result.summary_md_path,
            result_html=result.summary_html_path,
            result_meta=result.metadata_path,
            logger_override=logger,
        )
        # state 에 publish 결과 기록
        vod = result.vod_info
        channel_id = vod.channel_id if vod else None
        if pub_result is not None:
            state.update(
                result.video_no, status="completed",
                channel_id=channel_id,
                publish_status="success",
                publish_vod_count=pub_result.get("vod_count", 0),
            )
        else:
            # autorebuild 가 비활성화이거나 스킵된 경우
            if cfg.get("publish_autorebuild", False):
                state.update(
                    result.video_no, status="completed",
                    channel_id=channel_id,
                    publish_status="skipped_or_failed",
                )
    except Exception as e:
        logger.warning(f"자동 퍼블리시 중 예외 (무시): {e}")


def _cleanup_whisper_temp(video_path: str, work_dir: str, logger):
    """Whisper가 생성한 임시 WAV/분할 파일 정리"""
    import glob
    base = os.path.splitext(video_path)[0]
    # Whisper가 생성하는 임시 WAV 파일
    for pattern in [f"{base}*.wav", f"{base}*_part_*"]:
        for f in glob.glob(pattern):
            try:
                os.remove(f)
                logger.debug(f"  Whisper 임시 파일 삭제: {f}")
            except OSError:
                pass
    # work_dir 내 split 파일들
    for f in glob.glob(os.path.join(work_dir, "*.wav")):
        try:
            os.remove(f)
            logger.debug(f"  임시 WAV 삭제: {f}")
        except OSError:
            pass


def _cleanup_work_dir(work_dir: str, logger):
    """에러 발생 시 work_dir 내 임시 파일 정리"""
    if not os.path.isdir(work_dir):
        return
    for f in os.listdir(work_dir):
        fpath = os.path.join(work_dir, f)
        if os.path.isfile(fpath) and f.endswith((".mp4", ".wav", ".downloading")):
            try:
                os.remove(fpath)
                logger.info(f"  에러 정리: {fpath}")
            except OSError:
                pass


def process_vod(
    vod: VODInfo,
    cfg: dict,
    state: PipelineState,
    logger,
    limit_duration_sec: int = 0,
) -> PipelineResult:
    """단일 VOD 전체 파이프라인 처리.

    Args:
        limit_duration_sec: >0 이면 다운로드 후 앞부분만 잘라서 파이프라인 진행 (테스트용)
    """
    result = PipelineResult(video_no=vod.video_no, vod_info=vod)
    cookies = get_cookies(cfg)
    work_dir = os.path.join(cfg["work_dir"], vod.video_no)
    output_dir = cfg["output_dir"]
    os.makedirs(work_dir, exist_ok=True)

    try:
        # ── 1단계: 병렬 데이터 수집 ──
        result.stage = "collecting"
        state.update(vod.video_no, status="collecting", channel_id=vod.channel_id)
        logger.info(f"{'='*60}")
        logger.info(f"VOD 처리 시작: [{vod.video_no}] {vod.title}")
        logger.info(f"  길이: {format_duration(vod.duration)}, 카테고리: {vod.category}")
        logger.info(f"{'='*60}")

        with ThreadPoolExecutor(max_workers=3) as pool:
            # 다운로드, 채팅 수집, 커뮤니티 스크래핑 병렬 실행
            download_future = pool.submit(
                download_vod_144p, vod.video_no, cookies, work_dir
            )
            chat_future = pool.submit(
                fetch_all_chats, vod.video_no,
                max_duration_sec=limit_duration_sec,
            )
            # fmkorea 스크레이핑 (설정으로 비활성화 가능, B11: 오래된 VOD 자동 스킵)
            community_future = None
            skip_age, skip_reason = _should_skip_fmkorea(
                vod.publish_date, cfg.get("fmkorea_max_age_hours", 48)
            )
            if not cfg.get("fmkorea_enabled", True):
                logger.info("커뮤니티 수집 비활성화됨 (fmkorea_enabled=false)")
            elif skip_age:
                logger.info(f"커뮤니티 수집 스킵 (B11): {skip_reason}")
            else:
                community_future = pool.submit(
                    scrape_fmkorea,
                    cfg.get("fmkorea_search_keywords", [cfg.get("streamer_name", "")]),
                    max_pages=cfg.get("fmkorea_max_pages", 3),
                    max_posts=cfg.get("fmkorea_max_posts", 20),
                    broadcast_start=vod.publish_date,
                )

            # 결과 수집
            video_path = download_future.result()
            result.video_path = video_path
            logger.info(f"✓ 다운로드 완료: {video_path}")

            # 테스트 모드: 앞부분만 잘라서 이후 단계 진행
            if limit_duration_sec > 0:
                base, ext = os.path.splitext(video_path)
                clipped_path = f"{base}_clip{limit_duration_sec}s{ext}"
                clip_video(video_path, clipped_path, limit_duration_sec)
                video_path = clipped_path
                result.video_path = video_path
                logger.info(f"✓ 테스트 모드: 앞 {limit_duration_sec}초만 사용 → {video_path}")

            chats = chat_future.result()
            logger.info(f"✓ 채팅 수집 완료: {len(chats):,}개")

            community_posts = []
            if community_future:
                try:
                    community_posts = community_future.result()
                    result.community_posts = community_posts
                    logger.info(f"✓ 커뮤니티 수집 완료: {len(community_posts)}개 게시글")
                except Exception as e:
                    logger.warning(f"커뮤니티 수집 실패 (건너뜀): {e}")
            # else: 위에서 disabled / age-skip 사유를 이미 로깅함

        # 채팅 로그 저장
        if chats:
            chat_log_path = os.path.join(work_dir, f"{vod.video_no}_chat.log")
            save_chat_log(chats, chat_log_path)
            result.chat_log_path = chat_log_path

        # ── 2단계: 채팅 분석 ──
        result.stage = "analyzing"
        state.update(vod.video_no, status="analyzing", channel_id=vod.channel_id)

        highlights = []
        if chats:
            try:
                highlights = find_edit_points(chats)
                result.highlights = highlights
                logger.info(f"✓ 하이라이트 분석 완료: {len(highlights)}개 구간")
            except Exception as e:
                logger.error(f"채팅 하이라이트 분석 실패 (빈 highlights로 계속): {e}")
                highlights = []
        else:
            logger.warning("채팅 없음 → 하이라이트 분석 건너뜀")

        # ── 3단계: 자막 생성 ──
        result.stage = "transcribing"
        state.update(vod.video_no, status="transcribing", channel_id=vod.channel_id)

        # B05: 타임아웃/스톨 watchdog. cfg 미지정시 transcriber 의 기본값 사용.
        try:
            srt_path = transcribe_video(
                video_path,
                stall_sec=cfg.get("whisper_stall_sec", 600),
                timeout_sec=cfg.get("whisper_timeout_sec", 0),
            )
        except TimeoutError as e:
            logger.error(f"Whisper 타임아웃 → VOD 실패 처리: {e}")
            raise
        except Exception as e:
            logger.error(f"Whisper 실행 실패 → VOD 실패 처리: {e}")
            raise
        result.srt_path = srt_path
        logger.info(f"✓ 자막 생성 완료: {srt_path}")

        # Whisper 임시 파일 정리 (WAV, 분할 파일)
        _cleanup_whisper_temp(video_path, work_dir, logger)

        # ── 4단계: SRT 청크 분할 ──
        result.stage = "chunking"
        state.update(vod.video_no, status="chunking", channel_id=vod.channel_id)

        # Phase A2 precedence (pipeline/config.py DEFAULT_CONFIG 와 docstring 참조):
        #   chunk_max_tokens (not None) > chunk_max_chars.
        #   여기서는 chunk_srt() 에 두 값을 모두 전달하고 분기 결정은 chunker 가 맡는다.
        #   main.py 의 fallback 값은 DEFAULT_CONFIG 와 일치시킨다 (chunk_max_chars=8000, overlap=30).
        #   기존 하드코드 150000 은 Phase A2 에서 제거됨.
        chunks = chunk_srt(
            srt_path,
            max_chars=cfg.get("chunk_max_chars", 8000),
            overlap_sec=cfg.get("chunk_overlap_sec", 30),
            max_tokens=cfg.get("chunk_max_tokens"),
            tokenizer_encoding=cfg.get("chunk_tokenizer_encoding", "cl100k_base"),
            highlights=highlights,
            highlight_radius_sec=cfg.get("highlight_radius_sec", 300),
            cold_sample_sec=cfg.get("cold_sample_sec", 30),
        )
        logger.info(f"✓ 청크 분할 완료: {len(chunks)}개")

        if not chunks:
            logger.warning("SRT가 비어있어 요약을 건너뜁니다. 최소 리포트만 생성합니다.")
            result.stage = "completed"
            md_path, html_path, meta_path = generate_reports(
                "자막이 비어있어 요약을 생성할 수 없습니다.",
                vod, highlights, chats, output_dir,
            )
            result.summary_md_path = md_path
            result.summary_html_path = html_path
            result.metadata_path = meta_path
            state.update(vod.video_no, status="completed",
                         channel_id=vod.channel_id,
                         output_md=md_path, output_html=html_path)
            _try_auto_publish(cfg, result, state, logger)
            return result

        # ── 5단계: Claude 요약 ──
        result.stage = "summarizing"
        state.update(vod.video_no, status="summarizing", channel_id=vod.channel_id)

        claude_timeout = cfg.get("claude_timeout_sec", 300)
        claude_model = cfg.get("claude_model", "")

        chunk_results = process_chunks(
            chunks, highlights, chats, vod, claude_timeout,
            claude_model=claude_model,
        )
        logger.info(f"✓ 청크별 분석 완료: {len(chunk_results)}개")

        summary = merge_results(
            chunk_results, vod, community_posts, highlights, claude_timeout,
            srt_path=srt_path, claude_model=claude_model,
        )
        logger.info(f"✓ 통합 요약 생성 완료")

        # ── 6단계: 리포트 저장 ──
        result.stage = "saving"
        state.update(vod.video_no, status="saving", channel_id=vod.channel_id)

        md_path, html_path, meta_path = generate_reports(
            summary, vod, highlights, chats, output_dir,
            community_posts=community_posts,
        )
        result.summary_md_path = md_path
        result.summary_html_path = html_path
        result.metadata_path = meta_path

        # ── 완료 ──
        result.stage = "completed"
        state.update(
            vod.video_no,
            status="completed",
            channel_id=vod.channel_id,
            output_md=md_path,
            output_html=html_path,
        )

        logger.info(f"{'='*60}")
        logger.info(f"✓ VOD [{vod.video_no}] 처리 완료!")
        logger.info(f"  Markdown: {md_path}")
        logger.info(f"  HTML:     {html_path}")
        logger.info(f"{'='*60}")

        # 자동 퍼블리시
        _try_auto_publish(cfg, result, state, logger)

        # 임시 파일 정리
        if cfg.get("auto_cleanup", True) and video_path:
            try:
                os.remove(video_path)
                logger.info(f"  임시 영상 삭제: {video_path}")
            except OSError:
                pass

        return result

    except Exception as e:
        result.stage = "error"
        result.error = str(e)
        state.update(vod.video_no, status="error", channel_id=vod.channel_id, error=str(e))
        logger.error(f"VOD [{vod.video_no}] 처리 실패: {e}")
        logger.debug(traceback.format_exc())

        # 에러 시 임시 파일 정리
        if cfg.get("auto_cleanup", True):
            _cleanup_work_dir(work_dir, logger)

        return result


def run_daemon(cfg: dict):
    """데몬 모드: 주기적으로 새 VOD 폴링 후 처리 (멀티 스트리머 지원)"""
    log_dir = os.path.join(cfg["output_dir"], "logs")
    logger = setup_logging(log_dir)
    ensure_dirs(cfg)

    state_path = os.path.join(cfg["output_dir"], "pipeline_state.json")
    state = PipelineState(state_path)
    state.clear_stop()

    streamers = normalize_streamers(cfg)
    poll_interval = cfg.get("poll_interval_sec", 300)
    cookies = get_cookies(cfg)

    logger.info("=" * 60)
    logger.info("  Chzzk VOD 자동 모니터링 파이프라인 시작")
    logger.info(f"  스트리머 수: {len(streamers)}")
    for s in streamers:
        logger.info(f"    - {s['name']} (채널: {s['channel_id'][:8]}...)")
    logger.info(f"  폴링 간격: {poll_interval}초")
    logger.info(f"  출력 디렉터리: {cfg['output_dir']}")
    logger.info("=" * 60)

    if not validate_cookies(cfg):
        logger.error("쿠키가 설정되지 않았습니다. --setup-cookies로 설정하세요.")
        return

    while True:
        if state.should_stop():
            logger.info("종료 요청 감지. 파이프라인을 종료합니다.")
            break

        try:
            # B07: 스트리머별 cfg 빌더. 신규 폴링과 재시도가 동일 규칙을 공유한다.
            def _build_streamer_cfg(streamer: dict) -> dict:
                scfg = dict(cfg)
                if streamer.get("search_keywords"):
                    scfg["fmkorea_search_keywords"] = streamer["search_keywords"]
                if streamer.get("name"):
                    scfg["streamer_name"] = streamer["name"]
                return scfg

            # channel_id → streamer 인덱스 (재시도 시 cfg 복원용, B07)
            streamers_by_channel = {s["channel_id"]: s for s in streamers if s.get("channel_id")}

            for streamer in streamers:
                if state.should_stop():
                    break
                channel_id = streamer["channel_id"]
                logger.info(f"── 스트리머 폴링: {streamer['name']} ({channel_id[:8]}...) ──")

                # 스트리머별 검색 키워드를 cfg 에 임시 주입 (fmkorea 용)
                streamer_cfg = _build_streamer_cfg(streamer)

                new_vods = check_new_vods(channel_id, cookies, state, cfg=streamer_cfg)

                for vod in new_vods:
                    if state.should_stop():
                        break
                    process_vod(vod, streamer_cfg, state, logger)

            # 실패한 VOD 재시도
            failed = state.get_failed_vods(max_retries=3)
            for video_no, failed_channel_id in failed:
                if state.should_stop():
                    break
                logger.info(f"실패 VOD 재시도: {video_no}")
                retry_channel_id = failed_channel_id or cfg.get("target_channel_id", "")
                state.increment_retry(video_no, channel_id=retry_channel_id)
                try:
                    from content.network import NetworkManager
                    _, _, _, _, _, metadata = NetworkManager.get_video_info(video_no, cookies)
                    vod = VODInfo(
                        video_no=video_no,
                        title=metadata.get("title", ""),
                        channel_id=retry_channel_id,
                        channel_name=metadata.get("channelName", ""),
                        duration=metadata.get("duration", 0),
                        publish_date=metadata.get("createdDate", ""),
                        category=metadata.get("category", ""),
                        streamer_id=derive_streamer_id(retry_channel_id, metadata.get("channelName", "")),
                    )
                    # B07: 재시도 시에도 해당 스트리머 cfg 복원 (검색 키워드 등 유실 방지)
                    retry_streamer = streamers_by_channel.get(retry_channel_id)
                    if retry_streamer:
                        retry_cfg = _build_streamer_cfg(retry_streamer)
                    else:
                        # 알 수 없는 channel_id (스트리머 목록에서 제거됨) → 글로벌 cfg fallback
                        logger.warning(
                            f"재시도 채널 {retry_channel_id[:8]}... 이 현재 streamers 목록에 없음 → 글로벌 cfg 사용"
                        )
                        retry_cfg = cfg
                    process_vod(vod, retry_cfg, state, logger)
                except Exception as e:
                    logger.error(f"재시도 VOD 정보 조회 실패: {e}")

        except Exception as e:
            logger.error(f"메인 루프 오류: {e}")
            logger.debug(traceback.format_exc())

        logger.info(f"다음 폴링까지 {poll_interval}초 대기...")
        time.sleep(poll_interval)


def run_once(cfg: dict):
    """1회 실행: 새 VOD 확인 후 처리하고 종료 (멀티 스트리머 지원)"""
    log_dir = os.path.join(cfg["output_dir"], "logs")
    logger = setup_logging(log_dir)
    ensure_dirs(cfg)

    state_path = os.path.join(cfg["output_dir"], "pipeline_state.json")
    state = PipelineState(state_path)

    cookies = get_cookies(cfg)
    if not validate_cookies(cfg):
        return

    streamers = normalize_streamers(cfg)
    total_new = 0
    for streamer in streamers:
        channel_id = streamer["channel_id"]
        logger.info(f"── 스트리머: {streamer['name']} ({channel_id[:8]}...) ──")

        streamer_cfg = dict(cfg)
        if streamer.get("search_keywords"):
            streamer_cfg["fmkorea_search_keywords"] = streamer["search_keywords"]
            streamer_cfg["streamer_name"] = streamer["name"]

        new_vods = check_new_vods(channel_id, cookies, state, cfg=streamer_cfg)
        total_new += len(new_vods)
        for vod in new_vods:
            process_vod(vod, streamer_cfg, state, logger)

    if total_new == 0:
        logger.info("처리할 새 VOD가 없습니다.")


def run_single(video_no: str, cfg: dict, limit_duration_sec: int = 0):
    """특정 VOD 수동 처리"""
    log_dir = os.path.join(cfg["output_dir"], "logs")
    logger = setup_logging(log_dir)
    ensure_dirs(cfg)

    state_path = os.path.join(cfg["output_dir"], "pipeline_state.json")
    state = PipelineState(state_path)

    cookies = get_cookies(cfg)
    if not validate_cookies(cfg):
        return

    from content.network import NetworkManager
    logger.info(f"VOD {video_no} 정보 조회 중...")

    _, _, _, _, _, metadata = NetworkManager.get_video_info(video_no, cookies)
    channel_id = cfg.get("target_channel_id", "")
    channel_name = metadata.get("channelName", "")
    vod = VODInfo(
        video_no=video_no,
        title=metadata.get("title", ""),
        channel_id=channel_id,
        channel_name=channel_name,
        duration=metadata.get("duration", 0),
        publish_date=metadata.get("createdDate", ""),
        category=metadata.get("category", ""),
        streamer_id=derive_streamer_id(channel_id, channel_name),
    )

    process_vod(vod, cfg, state, logger, limit_duration_sec=limit_duration_sec)


def main():
    parser = argparse.ArgumentParser(description="Chzzk VOD 자동 모니터링 & 요약 파이프라인")
    parser.add_argument("--once", action="store_true", help="1회 실행 후 종료")
    parser.add_argument("--process", type=str, help="특정 VOD 번호를 수동 처리")
    parser.add_argument("--setup-cookies", action="store_true", help="쿠키 대화형 설정")
    parser.add_argument("--config", type=str, help="설정 파일 경로 (기본: pipeline_config.json)")
    parser.add_argument(
        "--limit-duration",
        type=int,
        default=0,
        help="(테스트용) 영상 앞부분 N초만 잘라서 처리. --process 와 함께 사용 (예: --limit-duration 1800 = 30분)",
    )
    args = parser.parse_args()

    if args.setup_cookies:
        interactive_cookie_setup()
        return

    try:
        cfg = load_config()
    except ConfigError as e:
        print("=" * 60)
        print("  ⚠  설정 파일 검증 실패")
        print("=" * 60)
        print(str(e))
        print()
        print("  설정을 수정한 뒤 다시 실행하세요.")
        print("  (기본값으로 초기화하려면 pipeline_config.json 을 삭제 후 재실행)")
        sys.exit(2)

    if args.process:
        run_single(args.process, cfg, limit_duration_sec=args.limit_duration)
    elif args.once:
        run_once(cfg)
    else:
        run_daemon(cfg)


if __name__ == "__main__":
    main()
