"""fmkorea 커뮤니티 스크레이핑

시간축 정렬 전략:
  - 커뮤니티 글의 시간은 wall-clock (실제 시계 시간)
  - VOD의 시간은 영상 시작 기준 상대 시간
  - 이 두 시간축은 본질적으로 다르므로, 커뮤니티 글은 '방송 시작 시각'을 기준으로
    대략적인 영상 내 위치를 추론하여 프롬프트에 명시
  - Claude에게 "이 데이터는 시간 동기화되지 않았음"을 명확히 전달
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from .models import CommunityPost
from .utils import retry

logger = logging.getLogger("pipeline")

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

REQUEST_DELAY = 2.5  # 요청 간 딜레이(초)


def _build_search_url(keyword: str, page: int = 1) -> str:
    encoded = quote_plus(keyword)
    return (
        f"https://www.fmkorea.com/search.php"
        f"?mid=ib&category=&search_keyword={encoded}"
        f"&search_target=title_content&page={page}"
    )


@retry(max_retries=2, backoff_base=3.0, exceptions=(requests.RequestException,))
def _fetch_page(url: str) -> Optional[str]:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _select_first(element, selectors: list[str]):
    """여러 CSS 셀렉터를 순서대로 시도하여 첫 매칭 반환"""
    for sel in selectors:
        result = element.select_one(sel)
        if result:
            return result
    return None


def _parse_relative_time(text: str) -> Optional[datetime]:
    """
    fmkorea 상대 시간 문자열을 datetime으로 변환.
    예: '5분 전', '2시간 전', '어제 14:30', '2026.04.14 15:00'
    """
    now = datetime.now(KST)
    text = text.strip()

    # 'N분 전'
    m = re.match(r"(\d+)분\s*전", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    # 'N시간 전'
    m = re.match(r"(\d+)시간\s*전", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    # 'N일 전'
    m = re.match(r"(\d+)일\s*전", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # 날짜 형식: 'YYYY.MM.DD HH:MM' 또는 'YYYY-MM-DD HH:MM'
    for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M", "%Y.%m.%d", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=KST)
        except ValueError:
            continue

    # 'MM.DD HH:MM' (올해 추정)
    m = re.match(r"(\d{1,2})[./](\d{1,2})\s+(\d{1,2}):(\d{2})", text)
    if m:
        month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)

    # '어제 HH:MM'
    m = re.match(r"어제\s+(\d{1,2}):(\d{2})", text)
    if m:
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)

    return None


def _parse_search_results(html: str) -> list[dict]:
    """검색 결과 페이지에서 게시글 목록 파싱.
    fmkorea 검색 결과 구조: table.bd_lst > tbody > tr
    컬럼: 카테고리(td.cate), 제목(td.title), 글쓴이(td.author), 시간(td.time), 조회(td.m_no), 추천
    """
    soup = BeautifulSoup(html, "lxml")
    posts = []

    # 메인 경로: table.bd_lst 기반
    table = soup.select_one("table.bd_lst")
    if table:
        rows = table.select("tbody tr")
        for row in rows:
            try:
                tds = row.select("td")
                if len(tds) < 5:
                    continue

                # 제목 td (class에 title 포함)
                title_td = row.select_one("td.title")
                if not title_td:
                    continue

                title_a = title_td.select_one("a.hx, a[href*='document_srl']")
                if not title_a:
                    continue

                title = title_a.get_text(strip=True)
                if not title or len(title) < 2:
                    continue

                href = title_a.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.fmkorea.com" + href

                # 댓글 수 (제목 옆 숫자)
                comments = 0
                comment_el = title_td.select_one("a.replyNum, span.rCount")
                if comment_el:
                    m = re.search(r"\d+", comment_el.get_text(strip=True))
                    if m:
                        comments = int(m.group())

                # 글쓴이
                author_td = row.select_one("td.author")
                author = author_td.get_text(strip=True) if author_td else ""

                # 시간
                time_td = row.select_one("td.time")
                raw_timestamp = time_td.get_text(strip=True) if time_td else ""
                parsed_time = _parse_relative_time(raw_timestamp) if raw_timestamp else None

                # 조회수 (첫 번째 td.m_no)
                views = 0
                view_tds = row.select("td.m_no")
                if view_tds:
                    m = re.search(r"\d+", view_tds[0].get_text(strip=True).replace(",", ""))
                    if m:
                        views = int(m.group())

                posts.append({
                    "title": title, "url": href, "body_preview": "",
                    "author": author, "timestamp": raw_timestamp,
                    "timestamp_parsed": parsed_time,
                    "views": views, "comments": comments,
                })
            except Exception as e:
                logger.debug(f"게시글 파싱 오류: {e}")
                continue

        return posts

    # 폴백: document_srl 링크 직접 탐색
    links = soup.select("a[href*='document_srl']")
    for link in links:
        title = link.get_text(strip=True)
        href = link.get("href", "")
        if title and len(title) > 5:
            if not href.startswith("http"):
                href = "https://www.fmkorea.com" + href
            posts.append({
                "title": title, "url": href, "body_preview": "",
                "author": "", "timestamp": "", "timestamp_parsed": None,
                "views": 0, "comments": 0,
            })

    return posts[:30]


def scrape_fmkorea(
    keywords: list[str],
    max_pages: int = 3,
    max_posts: int = 20,
    broadcast_start: Optional[str] = None,
) -> list[CommunityPost]:
    """
    fmkorea에서 키워드 검색 결과 수집.

    Args:
        keywords: 검색할 키워드 리스트
        max_pages: 키워드당 최대 페이지 수
        max_posts: 최종 반환할 최대 게시글 수
        broadcast_start: 방송 시작 시각 (ISO format). 제공 시 ±24시간 내 글만 필터링.
    """
    all_posts = []

    # 방송 시작 시각 파싱 (필터링용)
    broadcast_dt = None
    if broadcast_start:
        try:
            broadcast_dt = datetime.fromisoformat(broadcast_start.replace("Z", "+00:00"))
            if broadcast_dt.tzinfo is None:
                broadcast_dt = broadcast_dt.replace(tzinfo=KST)
        except (ValueError, TypeError):
            logger.warning(f"방송 시작 시각 파싱 실패: {broadcast_start}")

    for keyword in keywords:
        logger.info(f"fmkorea 검색: '{keyword}'")

        for page in range(1, max_pages + 1):
            url = _build_search_url(keyword, page)
            try:
                html = _fetch_page(url)
                if html is None:
                    break

                posts = _parse_search_results(html)
                if not posts:
                    logger.info(f"  페이지 {page}: 결과 없음")
                    break

                all_posts.extend(posts)
                logger.info(f"  페이지 {page}: {len(posts)}개 수집")

            except Exception as e:
                logger.warning(f"  페이지 {page} 수집 실패: {e}")
                break

            time.sleep(REQUEST_DELAY)

    # 중복 제거 (URL 기준)
    seen_urls = set()
    unique_posts = []
    for p in all_posts:
        if p["url"] not in seen_urls:
            seen_urls.add(p["url"])
            unique_posts.append(p)

    # 시간 기반 필터링 (방송 ±24시간)
    if broadcast_dt:
        window_start = broadcast_dt - timedelta(hours=24)
        window_end = broadcast_dt + timedelta(hours=24)
        filtered = []
        for p in unique_posts:
            pt = p.get("timestamp_parsed")
            if pt is None:
                filtered.append(p)  # 시간 파싱 실패한 글은 포함
            elif window_start <= pt <= window_end:
                filtered.append(p)
        logger.info(f"  시간 필터: {len(unique_posts)}개 → {len(filtered)}개 (±24시간)")
        unique_posts = filtered

    result_posts = unique_posts[:max_posts]
    logger.info(f"fmkorea 수집 완료: {len(result_posts)}개 게시글")

    return [
        CommunityPost(
            title=p["title"],
            url=p["url"],
            body_preview=p["body_preview"],
            author=p["author"],
            timestamp=p["timestamp"],
            views=p["views"],
            comments=p["comments"],
        )
        for p in result_posts
    ]


def format_community_for_prompt(
    posts: list[CommunityPost],
    broadcast_start: Optional[str] = None,
    max_chars: int = 5000,
) -> str:
    """
    커뮤니티 게시글을 프롬프트용 텍스트로 포맷.
    시간축 불일치를 명시적으로 알림.
    """
    if not posts:
        return "(커뮤니티 데이터 없음)"

    lines = []
    lines.append("⚠ 아래 커뮤니티 글은 '실제 시계 시간' 기준이며, 영상 타임코드와 직접 대응하지 않습니다.")
    if broadcast_start:
        lines.append(f"  방송 시작 시각: {broadcast_start} (이 시각을 기준으로 글의 시점을 추론하세요)")
    lines.append("")

    total_chars = sum(len(l) for l in lines)
    for i, p in enumerate(posts, 1):
        entry = f"{i}. [{p.timestamp}] {p.title} (조회 {p.views}, 댓글 {p.comments})"
        if p.body_preview:
            entry += f"\n   > {p.body_preview[:100]}"
        if total_chars + len(entry) > max_chars:
            lines.append(f"... 외 {len(posts) - i + 1}개 게시글")
            break
        lines.append(entry)
        total_chars += len(entry)

    return "\n".join(lines)
