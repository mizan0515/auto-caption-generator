"""fmkorea 커뮤니티 스크레이핑

시간축 정렬 전략:
  - 커뮤니티 글의 시간은 wall-clock (실제 시계 시간)
  - VOD의 시간은 영상 시작 기준 상대 시간
  - 이 두 시간축은 본질적으로 다르므로, 커뮤니티 글은 '방송 시작 시각'을 기준으로
    대략적인 영상 내 위치를 추론하여 프롬프트에 명시
  - Claude에게 "이 데이터는 시간 동기화되지 않았음"을 명확히 전달
"""

import logging
import random
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from .models import CommunityPost
from .utils import retry

logger = logging.getLogger("pipeline")

# B10: 세션 재사용 — 데몬 모드에서 매 스크랩마다 세션 생성 + 메인페이지 방문하던
# 비용을 줄인다. TTL 만료 또는 차단 발생 시 강제 갱신.
_SESSION_CACHE: dict = {"session": None, "last_main_visit": 0.0}
_SESSION_LOCK = threading.Lock()
_SESSION_TTL_SEC = 1800  # 30분 후 메인 페이지 재방문하여 쿠키 갱신

KST = timezone(timedelta(hours=9))

# B26: UA 로테이션 — fmkorea 가 장기적으로 같은 fingerprint 를 관찰하면
# 차단 가속. 세션 신규 생성 시마다 리스트에서 랜덤 선택하여 지문 분산.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

HEADERS = {
    "User-Agent": USER_AGENTS[0],  # 기본값. 세션 생성 시 random.choice 로 덮어씀.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    # Brotli(br) 은 requests 기본 설치에 포함 안 됨 — gzip/deflate 만 사용
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.fmkorea.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

# B26: 요청 간격 상향 (평균 10초, 최대 12초). 차단 확률 감소가 총 시간 증가보다 이득.
REQUEST_DELAY = 8.0   # 요청 간 기본 딜레이(초)
REQUEST_JITTER = 4.0  # 0~N 사이 랜덤 딜레이 추가

# B26: 430/429 한번 맞으면 같은 IP 로 즉시 재시도하면 차단 영구화 위험.
# work_dir 에 쿨다운 마커 파일을 남겨 N시간 동안 자동 수집을 스킵한다.
_COOLDOWN_FILENAME = ".fmkorea_cooldown"
_COOLDOWN_SEC = 3 * 3600  # 3시간


class FmkoreaBlocked(Exception):
    """fmkorea 안티봇 차단 감지 — 재시도 없이 즉시 중단"""
    pass


def _get_or_create_session() -> requests.Session:
    """캐시된 fmkorea 세션 반환. TTL 경과 시 메인 페이지 재방문으로 쿠키 갱신.

    호출자는 항상 이 함수를 통해 세션을 획득해야 cookies/last_main_visit 가
    일관되게 관리된다. 차단 감지 시 reset_fmkorea_session() 으로 강제 폐기.
    """
    with _SESSION_LOCK:
        sess = _SESSION_CACHE["session"]
        last = _SESSION_CACHE["last_main_visit"]
        now = time.time()
        needs_main_visit = sess is None or (now - last) > _SESSION_TTL_SEC

        if sess is None:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            # B26: 세션 신규 생성 시마다 UA 랜덤 선택 → fingerprint 분산
            sess.headers["User-Agent"] = random.choice(USER_AGENTS)
            _SESSION_CACHE["session"] = sess
            logger.debug(f"fmkorea 세션 신규 생성 (UA={sess.headers['User-Agent'][:40]}...)")

        if needs_main_visit:
            try:
                sess.get("https://www.fmkorea.com/", timeout=10)
                _SESSION_CACHE["last_main_visit"] = now
                time.sleep(1.5)
                logger.debug("fmkorea 메인 페이지 방문 (쿠키 갱신)")
            except requests.RequestException as e:
                logger.debug(f"fmkorea 메인 방문 실패 (무시, 캐시된 세션 그대로 사용): {e}")

        return sess


def _cooldown_path(work_dir: str) -> str:
    import os as _os
    return _os.path.join(work_dir, _COOLDOWN_FILENAME)


def _is_in_cooldown(work_dir: Optional[str]) -> bool:
    """B26: 직전 런에서 430/429 를 맞았다면 N시간 쿨다운. True 면 스크랩 스킵."""
    import os as _os
    if not work_dir:
        return False
    p = _cooldown_path(work_dir)
    if not _os.path.isfile(p):
        return False
    try:
        age = time.time() - _os.path.getmtime(p)
    except OSError:
        return False
    if age < _COOLDOWN_SEC:
        remaining_min = (_COOLDOWN_SEC - age) / 60
        logger.warning(
            f"fmkorea 쿨다운 중 (남은 {remaining_min:.0f}분) — 자동 수집 스킵. "
            f"필요 시 {p} 파일을 수동 삭제하거나 manual JSON 주입."
        )
        return True
    # 만료된 쿨다운 파일 정리
    try:
        _os.remove(p)
    except OSError:
        pass
    return False


def _mark_cooldown(work_dir: Optional[str]) -> None:
    """B26: 차단 감지 시 쿨다운 마커 생성."""
    import os as _os
    if not work_dir:
        return
    try:
        _os.makedirs(work_dir, exist_ok=True)
        p = _cooldown_path(work_dir)
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        logger.info(f"fmkorea 쿨다운 마커 생성: {p} ({_COOLDOWN_SEC//3600}시간 스킵)")
    except OSError as e:
        logger.debug(f"쿨다운 마커 생성 실패 (무시): {e}")


def reset_fmkorea_session() -> None:
    """차단 감지 등으로 세션을 폐기하고 다음 호출 시 새로 생성하도록 한다."""
    with _SESSION_LOCK:
        _SESSION_CACHE["session"] = None
        _SESSION_CACHE["last_main_visit"] = 0.0
    logger.debug("fmkorea 세션 캐시 리셋")


def _build_search_url(keyword: str, page: int = 1) -> str:
    encoded = quote_plus(keyword)
    return (
        f"https://www.fmkorea.com/search.php"
        f"?mid=ib&category=&search_keyword={encoded}"
        f"&search_target=title_content&page={page}"
    )


def _fetch_page(url: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """fmkorea 페이지 요청.

    - 430 / 429 등 레이트리밋 응답은 FmkoreaBlocked 로 즉시 중단 (재시도 무의미)
    - 그 외 네트워크 오류는 최대 2회 재시도
    """
    sess = session or requests
    last_err = None
    for attempt in range(2):
        try:
            resp = sess.get(url, headers=HEADERS, timeout=15)
            if resp.status_code in (429, 430):
                raise FmkoreaBlocked(f"HTTP {resp.status_code} (rate limit/anti-bot)")
            resp.raise_for_status()
            text = resp.text
            logger.debug(
                f"fmkorea 응답: status={resp.status_code}, len={len(text)}, "
                f"preview={text[:200].replace(chr(10), ' ')!r}"
            )
            return text
        except FmkoreaBlocked:
            raise
        except requests.RequestException as e:
            last_err = e
            if attempt == 0:
                time.sleep(3.0)
    raise last_err


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

                # 조회수 (첫 번째 td.m_no), 추천수 (td.m_no.m_no_voted)
                views = 0
                likes = 0
                m_no_tds = row.select("td.m_no")
                if m_no_tds:
                    m = re.search(r"\d+", m_no_tds[0].get_text(strip=True).replace(",", ""))
                    if m:
                        views = int(m.group())
                voted_td = row.select_one("td.m_no_voted") or (
                    m_no_tds[1] if len(m_no_tds) > 1 else None
                )
                if voted_td is not None:
                    m = re.search(r"\d+", voted_td.get_text(strip=True).replace(",", ""))
                    if m:
                        likes = int(m.group())

                posts.append({
                    "title": title, "url": href, "body_preview": "",
                    "author": author, "timestamp": raw_timestamp,
                    "timestamp_parsed": parsed_time,
                    "views": views, "comments": comments, "likes": likes,
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
                "views": 0, "comments": 0, "likes": 0,
            })

    return posts[:30]


def scrape_fmkorea(
    keywords: list[str],
    max_pages: int = 3,
    max_posts: int = 20,
    broadcast_start: Optional[str] = None,
    work_dir: Optional[str] = None,
    scraper_mode: str = "http",
) -> list[CommunityPost]:
    """
    fmkorea에서 키워드 검색 결과 수집.

    Args:
        keywords: 검색할 키워드 리스트
        max_pages: 키워드당 최대 페이지 수
        max_posts: 최종 반환할 최대 게시글 수
        broadcast_start: 방송 시작 시각 (ISO format). 제공 시 ±24시간 내 글만 필터링.
        work_dir: 쿨다운 마커(.fmkorea_cooldown) 저장 경로. 비우면 쿨다운 비활성.
        scraper_mode: "http" (기본, requests 기반) | "chromium" (미구현, 백로그 B27)
    """
    # B26: 직전 런에서 차단 맞았으면 쿨다운 동안 스킵
    if _is_in_cooldown(work_dir):
        return []

    # B27 (백로그): 실제 브라우저(Playwright) 기반 스크래퍼. 차단 회피 강화.
    if scraper_mode == "chromium":
        raise NotImplementedError(
            "scraper_mode='chromium' 은 아직 미구현입니다 (PIPELINE-BACKLOG B27). "
            "현재는 'http' 만 지원. pipeline_config.json 에서 "
            "fmkorea_scraper_mode 를 'http' 로 되돌리거나, 커뮤니티 자동 수집을 비활성화하세요."
        )
    if scraper_mode != "http":
        raise ValueError(
            f"알 수 없는 scraper_mode: {scraper_mode!r}. 'http' 또는 'chromium' 만 허용."
        )

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

    # B10: 캐시된 세션 재사용 (TTL 만료 시에만 메인 페이지 재방문)
    session = _get_or_create_session()

    blocked = False
    for keyword in keywords:
        if blocked:
            break
        logger.info(f"fmkorea 검색: '{keyword}'")

        for page in range(1, max_pages + 1):
            url = _build_search_url(keyword, page)
            try:
                html = _fetch_page(url, session=session)
                if html is None:
                    break

                posts = _parse_search_results(html)
                if not posts:
                    # 응답 내용 간단 검사 — 안티봇 / 차단 / 로그인 필요 페이지 구분
                    html_lower = html.lower()
                    hint = ""
                    if "captcha" in html_lower or "robot" in html_lower:
                        hint = " (CAPTCHA 또는 봇 감지 페이지로 추정)"
                    elif "login" in html_lower and "fmkorea" in html_lower and len(html) < 5000:
                        hint = " (로그인 리다이렉트로 추정)"
                    elif len(html) < 1000:
                        hint = f" (응답이 너무 짧음: {len(html)}바이트 — 차단 의심)"
                    logger.info(f"  페이지 {page}: 결과 없음{hint} (응답 {len(html):,}바이트)")
                    break

                all_posts.extend(posts)
                logger.info(f"  페이지 {page}: {len(posts)}개 수집")

            except FmkoreaBlocked as e:
                logger.warning(f"  ⚠ fmkorea 레이트리밋 감지 ({e}) — 추가 요청 중단")
                # B10: 차단 발생 시 세션 캐시 폐기 → 다음 스크랩은 새 세션으로 시도
                reset_fmkorea_session()
                # B26: 쿨다운 마커로 다음 런에서도 N시간 스킵 → IP 평판 회복 시간 확보
                _mark_cooldown(work_dir)
                blocked = True
                break
            except Exception as e:
                logger.warning(f"  페이지 {page} 수집 실패: {e}")
                break

            # 다음 요청까지 지터 포함 딜레이
            delay = REQUEST_DELAY + random.uniform(0, REQUEST_JITTER)
            time.sleep(delay)

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
            likes=p.get("likes", 0),
        )
        for p in result_posts
    ]


def save_community_posts(posts: list[CommunityPost], output_path: str) -> str:
    """커뮤니티 게시글을 JSON 으로 저장 (원자적 rename).

    재처리 시 fmkorea 재스크랩을 피하기 위한 사이드카.
    다른 Claude 모델로 재요약할 때 동일한 커뮤니티 입력을 보장 → 비교 공정성 확보.
    """
    import json
    import os as _os

    data = [
        {
            "title": p.title,
            "url": p.url,
            "body_preview": p.body_preview,
            "author": p.author,
            "timestamp": p.timestamp,
            "views": p.views,
            "comments": p.comments,
        }
        for p in posts
    ]
    tmp = output_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    _os.replace(tmp, output_path)
    logger.info(f"커뮤니티 JSON 저장: {output_path} ({len(posts)}개)")
    return output_path


def load_community_posts(video_no: str, work_dir: str) -> Optional[list[CommunityPost]]:
    """save_community_posts 로 저장된 JSON 을 로드. 없으면 None.

    RESUME/재요약 시 fmkorea 재스크랩을 건너뛰기 위해 사용.
    """
    import json
    import os as _os

    json_path = _os.path.join(work_dir, f"{video_no}_community.json")
    if not _os.path.isfile(json_path) or _os.path.getsize(json_path) == 0:
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            # 빈 리스트 저장은 스크랩 실패(레이트리밋 등)의 흔적일 가능성이 높다.
            # 성공적인 0-result 스크랩과 구분할 방법이 없으므로, 안전한 쪽으로
            # 캐시 미스 처리 → 다음 run 에서 재스크랩 기회를 준다.
            return None
        return [
            CommunityPost(
                title=d.get("title", ""),
                url=d.get("url", ""),
                body_preview=d.get("body_preview", ""),
                author=d.get("author", ""),
                timestamp=d.get("timestamp", ""),
                views=int(d.get("views") or 0),
                comments=int(d.get("comments") or 0),
                likes=int(d.get("likes") or 0),
            )
            for d in data
            if isinstance(d, dict)
        ]
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.warning(f"커뮤니티 JSON 로드 실패 → 재수집: {e}")
        return None


def load_manual_community_posts(video_no: str, work_dir: str) -> Optional[list[CommunityPost]]:
    """수동으로 수집한 커뮤니티 글 JSON override 를 로드한다.

    경로:
      work/<video_no>/<video_no>_community.manual.json

    이 파일이 존재하면 네트워크 스크랩보다 우선한다. anti-bot/430 발생 시
    사용자가 브라우저에서 직접 찾은 글 목록을 주입하기 위한 경로다.
    """
    import json
    import os as _os

    manual_path = _os.path.join(work_dir, f"{video_no}_community.manual.json")
    if not _os.path.isfile(manual_path) or _os.path.getsize(manual_path) == 0:
        return None

    try:
        with open(manual_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            logger.warning(f"수동 커뮤니티 JSON 이 비어있음: {manual_path}")
            return None
        posts = [
            CommunityPost(
                title=str(d.get("title", "")).strip(),
                url=str(d.get("url", "")).strip(),
                body_preview=str(d.get("body_preview", "")).strip(),
                author=str(d.get("author", "")).strip(),
                timestamp=str(d.get("timestamp", "")).strip(),
                views=int(d.get("views") or 0),
                comments=int(d.get("comments") or 0),
                likes=int(d.get("likes") or 0),
            )
            for d in data
            if isinstance(d, dict) and str(d.get("title", "")).strip()
        ]
        if not posts:
            logger.warning(f"수동 커뮤니티 JSON 에 유효한 title 이 없음: {manual_path}")
            return None
        logger.info(f"수동 커뮤니티 JSON 로드: {manual_path} ({len(posts)}개)")
        return posts
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"수동 커뮤니티 JSON 로드 실패: {manual_path} ({e})")
        return None


def format_community_for_prompt(
    posts: list[CommunityPost],
    broadcast_start: Optional[str] = None,
    max_chars: int = 8000,
    full_entry_top_n: int = 20,
) -> str:
    """
    커뮤니티 게시글을 프롬프트용 텍스트로 포맷.
    시간축 불일치를 명시적으로 알림.

    2단 구조로 주입:
      - Top N (engagement = views + comments*10 내림차순): title + body_preview 풀 엔트리
      - 나머지: 제목만 (압축) — 맥락 커버리지 확보 + 토큰 절약
    max_chars 에 걸리면 더 이상 추가하지 않고 요약 꼬리를 붙인다.
    """
    if not posts:
        return "(커뮤니티 데이터 없음)"

    def _engagement(p: CommunityPost) -> int:
        # 가중치 근거: fmkorea 에서 조회는 '노출'(제목 낚시에도 오름)이라 비중 낮춤.
        # 댓글은 관심 지표, 추천은 독자 승인(진짜 반응) 지표. 1 추천 ≈ 4 댓글 ≈ 1000 조회.
        return (p.views or 0) // 50 + (p.comments or 0) * 5 + (p.likes or 0) * 20

    ranked = sorted(posts, key=_engagement, reverse=True)
    top_posts = ranked[:full_entry_top_n]
    tail_posts = ranked[full_entry_top_n:]

    lines = []
    lines.append("⚠ 아래 커뮤니티 글은 '실제 시계 시간' 기준이며, 영상 타임코드와 직접 대응하지 않습니다.")
    if broadcast_start:
        lines.append(f"  방송 시작 시각: {broadcast_start} (이 시각을 기준으로 글의 시점을 추론하세요)")
    lines.append("")

    total_chars = sum(len(l) for l in lines)
    emitted = 0
    truncated_remaining = 0

    # Tier 1: 상위 engagement — 풀 엔트리
    if top_posts:
        lines.append("### 반응 많은 글 (본문 미리보기 포함)")
        total_chars += len(lines[-1])
        for i, p in enumerate(top_posts, 1):
            entry = f"{i}. [{p.timestamp}] {p.title} (추천 {p.likes}, 댓글 {p.comments}, 조회 {p.views})"
            if p.body_preview:
                entry += f"\n   > {p.body_preview[:100]}"
            if total_chars + len(entry) > max_chars:
                truncated_remaining = (len(top_posts) - i + 1) + len(tail_posts)
                break
            lines.append(entry)
            total_chars += len(entry)
            emitted += 1

    # Tier 2: 나머지 — 제목만
    if tail_posts and not truncated_remaining:
        lines.append("")
        lines.append("### 그 외 글 (제목만 — 추가 맥락 참고용)")
        total_chars += sum(len(l) for l in lines[-2:])
        for i, p in enumerate(tail_posts, 1):
            entry = f"- [{p.timestamp}] {p.title} (추천 {p.likes}, 댓글 {p.comments}, 조회 {p.views})"
            if total_chars + len(entry) > max_chars:
                truncated_remaining = len(tail_posts) - i + 1
                break
            lines.append(entry)
            total_chars += len(entry)
            emitted += 1

    if truncated_remaining:
        lines.append(f"... 외 {truncated_remaining}개 게시글 생략")

    return "\n".join(lines)
