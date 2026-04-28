"""B35 — 사용자 맥락 문서 (Context Document) 검증.

검증:
1. context_doc.load/save round-trip
2. 빈 내용 저장 → 파일 삭제 (반-삭제 동작)
3. cap 초과 시 잘림 + 로그
4. format_context_for_prompt 구조 (코드블록 격리)
5. fetch_context_from_url 분기:
   - HTTP 200 + 본문 충분 → 출처 라벨 + 본문
   - HTTP 200 + 본문 짧음 → ContextFetchError(severity="warning", debug=라벨된본문)
   - HTTP 200 + 본문 0 → ContextFetchError(severity="warning")
   - HTTP 404 → ContextFetchError(severity="error")
   - 잘못된 URL → ContextFetchError(severity="error")
   - requests 타임아웃 → ContextFetchError(severity="error")
6. _extract_text_from_html — script/style 제거 + p/h/li 추출
7. summarizer._build_chunk_user_prompt 가 context_doc 인자를 prompt 에 포함하는지
8. summarizer._build_chunk_user_prompt 가 context_doc=None 일 때 섹션 없는지
9. dashboard._context_apply_hint — 4 status 카테고리
"""

import sys
import tempfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import context_doc as cd  # noqa: E402


def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        path = cd.save_context_doc("100", td, "호종컵 룰: 4명 1팀 …")
        assert Path(path).is_file()
        loaded = cd.load_context_doc("100", td)
        assert loaded == "호종컵 룰: 4명 1팀 …"
    print("[1] save/load round-trip OK")


def test_save_empty_deletes_file():
    with tempfile.TemporaryDirectory() as td:
        cd.save_context_doc("100", td, "기존 내용")
        path = Path(cd.context_path("100", td))
        assert path.is_file()
        cd.save_context_doc("100", td, "")
        assert not path.is_file(), "빈 내용 저장 → 파일 삭제 기대"
        assert cd.load_context_doc("100", td) is None
    print("[2] 빈 내용 저장 → 파일 삭제 (반-삭제) OK")


def test_cap_truncation():
    with tempfile.TemporaryDirectory() as td:
        long_text = "가" * (cd.CAP_CHARS + 500)
        cd.save_context_doc("100", td, long_text)
        loaded = cd.load_context_doc("100", td)
        assert len(loaded) == cd.CAP_CHARS, f"cap={cd.CAP_CHARS}, got {len(loaded)}"
    print(f"[3] cap={cd.CAP_CHARS} 초과 → 잘림 OK")


def test_load_missing_returns_none():
    with tempfile.TemporaryDirectory() as td:
        assert cd.load_context_doc("999", td) is None
    print("[4] 파일 부재 → None OK")


def test_format_for_prompt_codeblock_isolation():
    txt = "호종컵 룰..."
    out = cd.format_context_for_prompt(txt)
    assert "## 추가 맥락" in out
    assert "```" in out
    assert txt in out
    # 코드블록 안에 있는지 확인
    code_start = out.index("```")
    code_end = out.rindex("```")
    assert code_start < out.index(txt) < code_end
    print("[5] format → 코드블록 격리 + 섹션 헤더 OK")


def test_format_for_prompt_empty_returns_blank():
    assert cd.format_context_for_prompt("") == ""
    assert cd.format_context_for_prompt(None) == ""
    assert cd.format_context_for_prompt("   ") == ""
    print("[6] 빈 context → 빈 문자열 (섹션 X) OK")


def test_fetch_url_invalid_scheme():
    try:
        cd.fetch_context_from_url("ftp://example.com")
    except cd.ContextFetchError as e:
        assert e.severity == "error"
        print("[7] http/https 외 scheme → error OK")
        return
    raise AssertionError("scheme 거부 안 됨")


def test_fetch_url_empty():
    try:
        cd.fetch_context_from_url("")
    except cd.ContextFetchError as e:
        assert e.severity == "error"
        print("[8] 빈 URL → error OK")
        return
    raise AssertionError("빈 URL 거부 안 됨")


def test_fetch_url_404():
    """requests.get 을 모킹하여 404 응답 시뮬"""
    fake_resp = mock.MagicMock()
    fake_resp.status_code = 404
    fake_resp.text = "<html>not found</html>"
    with mock.patch("requests.get", return_value=fake_resp):
        try:
            cd.fetch_context_from_url("https://example.com/x")
        except cd.ContextFetchError as e:
            assert e.severity == "error"
            assert "404" in e.user_msg
            print("[9] HTTP 404 → error 'HTTP 404' 메시지 OK")
            return
    raise AssertionError("404 거부 안 됨")


def test_fetch_url_short_body_warning():
    """본문이 짧으면 warning + debug 에 라벨된 본문"""
    fake_resp = mock.MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "<html><p>짧다</p></html>"
    with mock.patch("requests.get", return_value=fake_resp):
        try:
            cd.fetch_context_from_url("https://example.com/x")
        except cd.ContextFetchError as e:
            assert e.severity == "warning"
            assert "[출처: https://example.com/x]" in e.debug
            assert "짧다" in e.debug
            print("[10] 짧은 본문 → warning + debug 에 라벨된 본문 OK")
            return
    raise AssertionError("짧은 본문 warning 안 발생")


def test_fetch_url_full_body():
    """본문이 충분히 길면 정상 반환 ([출처:...]\\n\\n<body>)"""
    body = "p" + "x" * 600  # > SHORT_BODY_THRESHOLD
    fake_resp = mock.MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = f"<html><p>{body}</p></html>"
    with mock.patch("requests.get", return_value=fake_resp):
        out = cd.fetch_context_from_url("https://example.com/x")
        assert out.startswith("[출처: https://example.com/x]")
        assert body in out
    print("[11] 본문 충분 → 출처 라벨 + 본문 OK")


def test_fetch_url_timeout():
    import requests as _requests
    with mock.patch("requests.get", side_effect=_requests.Timeout("slow")):
        try:
            cd.fetch_context_from_url("https://example.com/x", timeout=1.0)
        except cd.ContextFetchError as e:
            assert e.severity == "error"
            assert "타임아웃" in e.user_msg
            print("[12] requests.Timeout → error '타임아웃' OK")
            return
    raise AssertionError("타임아웃 분기 안 잡힘")


def test_extract_text_strips_script_style():
    html = """<html>
    <head><style>body{color:red;}</style></head>
    <body>
    <script>alert('boo')</script>
    <h1>제목</h1>
    <p>본문 한 줄</p>
    <li>리스트 항목</li>
    </body></html>"""
    text = cd._extract_text_from_html(html)
    assert "alert" not in text
    assert "color:red" not in text
    assert "제목" in text
    assert "본문 한 줄" in text
    assert "리스트 항목" in text
    print("[13] HTML 추출 — script/style 제거 + 본문 태그 추출 OK")


def test_summarizer_chunk_prompt_includes_context():
    from pipeline.summarizer import _build_chunk_user_prompt
    from pipeline.models import VODInfo
    chunk = {
        "index": 1, "start_ms": 0, "end_ms": 60_000,
        "start_hhmmss": "00:00:00", "end_hhmmss": "00:01:00",
        "char_count": 100, "text": "자막 본문",
    }
    vod = VODInfo(
        video_no="100", title="t", channel_id="c", channel_name="n",
        duration=60, publish_date="2026-04-26T17:05:10+09:00",
        thumbnail_url="", category="",
    )
    out = _build_chunk_user_prompt(
        chunk, [], [], vod, lexicon_terms=None,
        context_doc="호종컵 룰: 4명 1팀",
    )
    assert "## 추가 맥락" in out
    assert "호종컵 룰: 4명 1팀" in out
    # 데이터/지시 격리 — 코드블록 안
    code_start = out.index("```")
    assert code_start < out.index("호종컵 룰")
    print("[14] summarizer chunk prompt 에 context 인용 블록 포함 OK")


def test_summarizer_chunk_prompt_no_context_section_when_none():
    from pipeline.summarizer import _build_chunk_user_prompt
    from pipeline.models import VODInfo
    chunk = {
        "index": 1, "start_ms": 0, "end_ms": 60_000,
        "start_hhmmss": "00:00:00", "end_hhmmss": "00:01:00",
        "char_count": 100, "text": "자막 본문",
    }
    vod = VODInfo(
        video_no="100", title="t", channel_id="c", channel_name="n",
        duration=60, publish_date="", thumbnail_url="", category="",
    )
    out = _build_chunk_user_prompt(chunk, [], [], vod, context_doc=None)
    assert "## 추가 맥락" not in out
    print("[15] context_doc=None 이면 추가 맥락 섹션 없음 OK")


def test_dashboard_status_apply_hint_categories():
    from pipeline.dashboard import Dashboard
    inst = Dashboard.__new__(Dashboard)
    pre = inst._context_apply_hint("transcribing")
    during = inst._context_apply_hint("summarizing")
    post_done = inst._context_apply_hint("completed")
    err = inst._context_apply_hint("error")
    assert "곧 요약 단계" in pre[0]
    assert "이미 요약" in during[0]
    assert "재처리" in post_done[0]
    assert "재처리" in err[0] or "재시도" in err[0]
    print("[16] dashboard _context_apply_hint 4 카테고리 분기 OK")


def main():
    test_save_load_roundtrip()
    test_save_empty_deletes_file()
    test_cap_truncation()
    test_load_missing_returns_none()
    test_format_for_prompt_codeblock_isolation()
    test_format_for_prompt_empty_returns_blank()
    test_fetch_url_invalid_scheme()
    test_fetch_url_empty()
    test_fetch_url_404()
    test_fetch_url_short_body_warning()
    test_fetch_url_full_body()
    test_fetch_url_timeout()
    test_extract_text_strips_script_style()
    test_summarizer_chunk_prompt_includes_context()
    test_summarizer_chunk_prompt_no_context_section_when_none()
    test_dashboard_status_apply_hint_categories()
    print("\nb35_context_doc: 16/16 OK")


if __name__ == "__main__":
    main()
