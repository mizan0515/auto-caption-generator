"""헤드리스 144p VOD 다운로더 (Qt 의존성 없음)"""

import logging
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# 기존 모듈 재사용을 위해 프로젝트 루트를 sys.path에 추가
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from content.network import NetworkManager

from .config import get_cookies
from .utils import retry, format_size, sanitize_filename

logger = logging.getLogger("pipeline")

HEADERS = {"User-Agent": "Mozilla/5.0"}
CHUNK_SIZE = 1024 * 1024  # 1MB per read
PART_SIZE = 10 * 1024 * 1024  # 10MB per download part


@retry(max_retries=3, backoff_base=2.0, exceptions=(requests.RequestException,))
def _get_content_length(url: str) -> int:
    resp = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
    resp.raise_for_status()
    return int(resp.headers.get("Content-Length", 0))


def _download_range(url: str, start: int, end: int, dest_path: str, part_num: int) -> int:
    """바이트 범위 다운로드"""
    range_header = {"Range": f"bytes={start}-{end}", **HEADERS}
    resp = requests.get(url, headers=range_header, stream=True, timeout=60)
    resp.raise_for_status()

    written = 0
    with open(dest_path, "r+b") as f:
        f.seek(start)
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)
                written += len(chunk)
    return written


def _download_direct(url: str, dest_path: str, progress_func=None) -> str:
    """HTTP Range 기반 멀티스레드 다운로드.

    `.downloading` 임시 파일에 쓰고 모든 파트가 성공한 뒤에야 최종 이름으로 변경한다.
    중간 실패 시 임시 파일이 남아 있으면 다음 실행에서 정리되도록 한다.
    """
    total_size = _get_content_length(url)
    if total_size == 0:
        raise RuntimeError("Content-Length가 0입니다. URL을 확인하세요.")

    logger.info(f"다운로드 시작: {format_size(total_size)}")

    tmp_path = dest_path + ".downloading"

    try:
        # 임시 파일을 미리 total_size 로 확장
        with open(tmp_path, "wb") as f:
            f.truncate(total_size)

        # 파트 분할
        parts = []
        offset = 0
        part_num = 0
        while offset < total_size:
            end = min(offset + PART_SIZE - 1, total_size - 1)
            parts.append((offset, end, part_num))
            offset = end + 1
            part_num += 1

        downloaded = 0
        max_workers = min(4, len(parts))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_download_range, url, start, end, tmp_path, pn): (start, end, pn)
                for start, end, pn in parts
            }
            for future in as_completed(futures):
                start, end, pn = futures[future]
                try:
                    written = future.result()
                    downloaded += written
                    pct = downloaded / total_size * 100
                    logger.debug(f"  파트 {pn}: {format_size(written)} 완료 ({pct:.1f}%)")
                    if progress_func:
                        progress_func(downloaded, total_size)
                except Exception as e:
                    logger.error(f"  파트 {pn} 다운로드 실패: {e}")
                    raise

        # 모든 파트 완료 후 최종 이름으로 변경
        os.replace(tmp_path, dest_path)
        logger.info(f"다운로드 완료: {dest_path} ({format_size(total_size)})")
        return dest_path

    except Exception:
        # 실패 시 불완전 파일 삭제
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.info(f"  불완전 다운로드 파일 삭제: {tmp_path}")
            except OSError as e:
                logger.warning(f"  불완전 파일 삭제 실패: {e}")
        raise


def _download_m3u8(m3u8_url: str, dest_path: str, progress_func=None) -> str:
    """m3u8 세그먼트 다운로드 후 병합. 불완전 다운로드 시 파일 삭제."""
    logger.info(f"m3u8 다운로드 시작: {m3u8_url}")

    resp = requests.get(m3u8_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    lines = resp.text.splitlines()
    segments = [line.strip() for line in lines if line.strip() and not line.startswith("#")]

    if not segments:
        raise RuntimeError("m3u8에서 세그먼트를 찾을 수 없습니다.")

    logger.info(f"  세그먼트 {len(segments)}개 발견")

    from urllib.parse import urljoin
    base_url = m3u8_url.rsplit("/", 1)[0] + "/"
    segment_urls = []
    for seg in segments:
        if seg.startswith("http"):
            segment_urls.append(seg)
        else:
            segment_urls.append(urljoin(base_url, seg))

    # 다운로드 중임을 표시하는 임시 확장자 사용
    tmp_path = dest_path + ".downloading"
    try:
        with open(tmp_path, "wb") as out_f:
            for i, seg_url in enumerate(segment_urls):
                try:
                    with requests.get(seg_url, headers=HEADERS, timeout=60, stream=True) as seg_resp:
                        seg_resp.raise_for_status()
                        for chunk in seg_resp.iter_content(chunk_size=CHUNK_SIZE):
                            if chunk:
                                out_f.write(chunk)
                except requests.RequestException as e:
                    logger.warning(f"  세그먼트 {i} 다운로드 실패, 재시도: {e}")
                    with requests.get(seg_url, headers=HEADERS, timeout=60, stream=True) as seg_resp:
                        seg_resp.raise_for_status()
                        for chunk in seg_resp.iter_content(chunk_size=CHUNK_SIZE):
                            if chunk:
                                out_f.write(chunk)

                if progress_func:
                    progress_func(i + 1, len(segment_urls))

                if (i + 1) % 100 == 0:
                    logger.info(f"  세그먼트 {i + 1}/{len(segment_urls)} 완료")

        # 모든 세그먼트 완료 후 최종 이름으로 변경
        os.replace(tmp_path, dest_path)
        logger.info(f"m3u8 다운로드 완료: {dest_path}")
        return dest_path

    except Exception:
        # 실패 시 불완전 파일 삭제 (cleanup 실패가 원본 예외를 가리지 않도록 OSError 보호)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.info(f"  불완전 다운로드 파일 삭제: {tmp_path}")
            except OSError as e:
                logger.warning(f"  불완전 파일 삭제 실패: {e}")
        raise


def download_vod_144p(
    video_no: str,
    cookies: dict,
    output_dir: str,
    progress_func=None,
) -> str:
    """
    VOD를 144p로 다운로드.
    DASH → m3u8 순서로 시도.
    반환: 다운로드된 파일 경로
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. 비디오 정보 조회
    logger.info(f"VOD 정보 조회: {video_no}")
    video_id, in_key, adult, vod_status, live_rewind_json, metadata = \
        NetworkManager.get_video_info(video_no, cookies)

    title = sanitize_filename(metadata.get("title", video_no))
    filename = f"{video_no}_{title}_144p.mp4"
    dest_path = os.path.join(output_dir, filename)

    # 이전 실행에서 남은 불완전 다운로드 파일 정리
    stale_tmp = dest_path + ".downloading"
    if os.path.exists(stale_tmp):
        try:
            os.remove(stale_tmp)
            logger.info(f"이전 불완전 다운로드 삭제: {stale_tmp}")
        except OSError as e:
            # 파일이 잠겨있으면 이번 실행은 새 임시 이름으로 진행하기보다 즉시 실패시킨다
            # (잠긴 파일을 그대로 두면 다음 실행에서도 같은 문제 반복).
            raise RuntimeError(
                f"이전 불완전 다운로드 파일을 삭제할 수 없습니다: {stale_tmp} ({e})"
            )

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        logger.info(f"이미 다운로드됨: {dest_path}")
        return dest_path

    # 2. DASH 매니페스트 시도
    if video_id and in_key:
        try:
            sorted_reps, auto_res, auto_url = \
                NetworkManager.get_video_dash_manifest(video_id, in_key)

            if not sorted_reps:
                raise RuntimeError("DASH 매니페스트에 해상도 정보 없음")

            # 가장 낮은 해상도 선택 (144p에 가장 가까운)
            target_rep = sorted_reps[0]  # [resolution, base_url]
            target_res, target_url = target_rep
            logger.info(f"DASH: {target_res}p 해상도 선택 (URL 획득)")

            return _download_direct(target_url, dest_path, progress_func)
        except Exception as e:
            logger.warning(f"DASH 다운로드 실패, m3u8 폴백: {e}")

    # 3. m3u8 폴백
    if live_rewind_json:
        try:
            target_resolution = 144
            sorted_reps, _, _ = NetworkManager.get_video_m3u8_manifest(live_rewind_json)
            # 가장 가까운 낮은 해상도 선택
            best_rep = sorted_reps[0]
            for rep in sorted_reps:
                if rep[0] <= target_resolution:
                    best_rep = rep
            target_res = best_rep[0]

            m3u8_url = NetworkManager.get_video_m3u8_base_url(live_rewind_json, target_res)
            logger.info(f"m3u8: {target_res}p 해상도 선택")

            return _download_m3u8(m3u8_url, dest_path, progress_func)
        except Exception as e:
            logger.error(f"m3u8 다운로드도 실패: {e}")
            raise

    raise RuntimeError(f"VOD {video_no}의 다운로드 URL을 찾을 수 없습니다.")
