"""Headless 144p VOD downloader."""

import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from content.network import NetworkManager
from split_video import get_duration

from .utils import clip_video, format_size, sanitize_filename, retry

logger = logging.getLogger("pipeline")

HEADERS = {"User-Agent": "Mozilla/5.0"}
CHUNK_SIZE = 1024 * 1024
PART_SIZE = 10 * 1024 * 1024


def _is_valid_media_file(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0 and get_duration(path) > 0
    except Exception as exc:
        logger.warning(f"손상된 미디어 캐시 감지, 재다운로드 예정: {path} ({exc})")
        return False


@retry(max_retries=3, backoff_base=2.0, exceptions=(requests.RequestException,))
def _get_content_length(url: str) -> int:
    resp = requests.head(url, headers=HEADERS, timeout=15, allow_redirects=True)
    resp.raise_for_status()
    return int(resp.headers.get("Content-Length", 0))


def _download_range(url: str, start: int, end: int, dest_path: str, part_num: int) -> int:
    del part_num
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
    total_size = _get_content_length(url)
    if total_size == 0:
        raise RuntimeError("Content-Length가 0입니다. URL을 확인하세요.")

    logger.info(f"다운로드 시작: {format_size(total_size)}")
    tmp_path = dest_path + ".downloading"

    try:
        with open(tmp_path, "wb") as f:
            f.truncate(total_size)

        parts = []
        offset = 0
        part_num = 0
        while offset < total_size:
            end = min(offset + PART_SIZE - 1, total_size - 1)
            parts.append((offset, end, part_num))
            offset = end + 1
            part_num += 1

        downloaded = 0
        with ThreadPoolExecutor(max_workers=min(4, len(parts))) as pool:
            futures = {
                pool.submit(_download_range, url, start, end, tmp_path, pn): (start, end, pn)
                for start, end, pn in parts
            }
            for future in as_completed(futures):
                start, end, pn = futures[future]
                del start, end
                try:
                    written = future.result()
                except Exception as e:
                    logger.error(f"  파트 {pn} 다운로드 실패: {e}")
                    raise
                downloaded += written
                if progress_func:
                    progress_func(downloaded, total_size)

        os.replace(tmp_path, dest_path)
        logger.info(f"다운로드 완료: {dest_path} ({format_size(total_size)})")
        return dest_path
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                logger.info(f"  불완전 다운로드 파일 삭제: {tmp_path}")
            except OSError as e:
                logger.warning(f"  불완전 파일 삭제 실패: {e}")
        raise


def _load_m3u8_segments(m3u8_url: str) -> list[tuple[float, str]]:
    resp = requests.get(m3u8_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    from urllib.parse import urljoin

    base_url = m3u8_url.rsplit("/", 1)[0] + "/"
    segments: list[tuple[float, str]] = []
    pending_duration = 0.0
    for raw in resp.text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MAP:"):
            match = re.search(r'URI="([^"]+)"', line)
            if not match:
                continue
            map_url = match.group(1)
            url = map_url if map_url.startswith("http") else urljoin(base_url, map_url)
            segments.append((0.0, url))
            continue
        if line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
            except ValueError:
                pending_duration = 0.0
            continue
        if line.startswith("#"):
            continue
        url = line if line.startswith("http") else urljoin(base_url, line)
        segments.append((pending_duration, url))
        pending_duration = 0.0
    return segments


def _download_m3u8(
    m3u8_url: str,
    dest_path: str,
    progress_func=None,
    start_sec: int = 0,
    duration_sec: int = 0,
) -> str:
    logger.info(f"m3u8 다운로드 시작: {m3u8_url}")
    all_segments = _load_m3u8_segments(m3u8_url)
    if not all_segments:
        raise RuntimeError("m3u8에서 세그먼트를 찾을 수 없습니다.")

    segment_urls: list[str] = []
    if start_sec > 0 or duration_sec > 0:
        end_sec = start_sec + duration_sec if duration_sec > 0 else float("inf")
        cursor = 0.0
        media_started = False
        for seg_duration, seg_url in all_segments:
            if seg_duration <= 0 and not media_started:
                segment_urls.append(seg_url)
                continue
            next_cursor = cursor + max(seg_duration, 0.0)
            overlaps = next_cursor > start_sec and cursor < end_sec
            if overlaps:
                segment_urls.append(seg_url)
                media_started = True
            cursor = next_cursor
            if media_started and cursor >= end_sec:
                break
        logger.info(
            f"  세그먼트 {len(segment_urls)}개 선택 "
            f"(slice {start_sec}s..{('end' if duration_sec <= 0 else end_sec)})"
        )
    else:
        segment_urls = [seg_url for _, seg_url in all_segments]
        logger.info(f"  세그먼트 {len(segment_urls)}개 발견")

    if not segment_urls:
        raise RuntimeError("요청한 시간 범위에 해당하는 m3u8 세그먼트가 없습니다.")

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

        if not _is_valid_media_file(tmp_path):
            raise RuntimeError(f"m3u8 download produced invalid media file: {tmp_path}")
        os.replace(tmp_path, dest_path)
        logger.info(f"m3u8 다운로드 완료: {dest_path}")
        return dest_path
    except Exception:
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
    start_sec: int = 0,
    duration_sec: int = 0,
    filename_suffix: str = "",
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    logger.info(f"VOD 정보 조회: {video_no}")
    video_id, in_key, adult, vod_status, live_rewind_json, metadata = NetworkManager.get_video_info(video_no, cookies)
    del adult, vod_status

    title = sanitize_filename(metadata.get("title", video_no))
    suffix = filename_suffix or ""
    filename = f"{video_no}_{title}_144p{suffix}.mp4"
    dest_path = os.path.join(output_dir, filename)
    stale_tmp = dest_path + ".downloading"

    if os.path.exists(stale_tmp):
        try:
            stale_size = os.path.getsize(stale_tmp)
            if stale_size > 0 and not os.path.exists(dest_path):
                os.replace(stale_tmp, dest_path)
                logger.info(f"기존 임시 파일 복구: {dest_path} ({format_size(stale_size)})")
                return dest_path
            os.remove(stale_tmp)
            logger.info(f"이전 불완전 다운로드 삭제: {stale_tmp}")
        except OSError as e:
            raise RuntimeError(
                f"이전 불완전 다운로드 파일을 정리할 수 없습니다: {stale_tmp} ({e})"
            ) from e

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        if not _is_valid_media_file(dest_path):
            try:
                os.remove(dest_path)
            except OSError as exc:
                raise RuntimeError(f"invalid cached media could not be removed: {dest_path} ({exc})") from exc
        else:
            logger.info(f"이미 다운로드됨: {dest_path}")
            return dest_path

    slice_requested = start_sec > 0 or duration_sec > 0
    if slice_requested:
        import glob

        full_candidates = [
            path for path in glob.glob(os.path.join(output_dir, f"{video_no}_*_144p.mp4"))
            if path != dest_path and _is_valid_media_file(path)
        ]
        if full_candidates and duration_sec > 0:
            full_candidates.sort(key=os.path.getmtime, reverse=True)
            source_path = full_candidates[0]
            logger.info(f"기존 전체 mp4에서 슬라이스 재사용: {source_path}")
            return clip_video(source_path, dest_path, duration_sec, start_sec=start_sec)

    if video_id and in_key and not slice_requested:
        try:
            sorted_reps, auto_res, auto_url = NetworkManager.get_video_dash_manifest(video_id, in_key)
            del auto_res, auto_url
            if not sorted_reps:
                raise RuntimeError("DASH 매니페스트에 해상도 정보가 없습니다.")

            target_res, target_url = sorted_reps[0]
            logger.info(f"DASH: {target_res}p 해상도 선택")
            return _download_direct(target_url, dest_path, progress_func)
        except Exception as e:
            logger.warning(f"DASH 다운로드 실패, m3u8 폴백: {e}")

    if live_rewind_json:
        try:
            sorted_reps, _, _ = NetworkManager.get_video_m3u8_manifest(live_rewind_json)
            best_rep = sorted_reps[0]
            for rep in sorted_reps:
                if rep[0] <= 144:
                    best_rep = rep
            target_res = best_rep[0]
            m3u8_url = NetworkManager.get_video_m3u8_base_url(live_rewind_json, target_res)
            logger.info(f"m3u8: {target_res}p 해상도 선택")
            return _download_m3u8(
                m3u8_url,
                dest_path,
                progress_func,
                start_sec=start_sec,
                duration_sec=duration_sec,
            )
        except Exception as e:
            logger.error(f"m3u8 다운로드도 실패: {e}")
            raise

    raise RuntimeError(f"VOD {video_no}의 다운로드 URL을 찾을 수 없습니다.")
